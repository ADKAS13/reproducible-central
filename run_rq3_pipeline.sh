#!/usr/bin/env bash
# run_rq3_pipeline.sh
#
# Runs rebuild.sh for buildspecs matching *rq3*.buildspec.
# On genuine compilation/dependency failure, streams log to rq3_exec.py,
# modifies pom.xml in place, and retries.

set -uo pipefail

PATTERN="${1:-*rq3.buildspec}"
RC_ROOT="$(pwd)"
REBUILD_SH="${RC_ROOT}/rebuild.sh"
LLM_FIXER="${RC_ROOT}/scripts/rq3_exec.py"
LOG_DIR="${RC_ROOT}/rq3_logs"

mkdir -p "$LOG_DIR"

echo "======================================================"
echo "  RQ3 Pipeline — Direct pom.xml Fix & Retry"
echo "  Pattern: ${PATTERN}"
echo "======================================================"

# Find buildspecs matching case-insensitive 'rq3'
mapfile -t BUILDSPECS < <(find "${RC_ROOT}" -iname "${PATTERN}" | sort)

if [ ${#BUILDSPECS[@]} -eq 0 ]; then
    echo "ERROR: No buildspecs found matching pattern: ${PATTERN}"
    exit 1
fi

PASS=0
FIXED=0
FAIL=0

for spec in "${BUILDSPECS[@]}"; do
    REPO_DIR=$(dirname "$spec")
    REPO_NAME=$(basename "$REPO_DIR")
    SPEC_NAME=$(basename "$spec")
    
    echo "------------------------------------------------------"
    echo "[BUILD ATTEMPT 1] ${REPO_NAME}/${SPEC_NAME}"

    ATTEMPT1_LOG="${LOG_DIR}/${REPO_NAME}_${SPEC_NAME%.buildspec}_attempt1.log"

    # Run initial build
    bash "${REBUILD_SH}" "$spec" 2>&1 | tee "$ATTEMPT1_LOG"

    # Inspect log for REAL compilation/dependency failure (ignoring buildinfo output diffs)
    if grep -qE "BUILD FAILURE|Compilation failure|Could not resolve dependencies|Could not find artifact" "$ATTEMPT1_LOG"; then
        echo "        -> [RESULT]: Real build failure detected. Invoking LLM Fixer..."

        # Locate pom.xml inside the repository build cache directory
        POM_PATH=$(find "$REPO_DIR" -name "pom.xml" -not -path "*/target/*" | head -n 1)

        if [ -z "$POM_PATH" ]; then
            echo "        -> [ERROR]: Could not locate pom.xml in $REPO_DIR"
            ((FAIL++)) || true
            continue
        fi

        # Pass log and pom.xml path to Python fixer
        if cat "$ATTEMPT1_LOG" | python3 "${LLM_FIXER}" --pom "$POM_PATH"; then
            echo "        -> [RESULT]: pom.xml modified. Retrying build..."

            ATTEMPT2_LOG="${LOG_DIR}/${REPO_NAME}_${SPEC_NAME%.buildspec}_attempt2.log"
            
            # Note: If rebuild.sh runs git reset, also add the patch to execBefore in the spec
            bash "${REBUILD_SH}" "$spec" 2>&1 | tee "$ATTEMPT2_LOG"

            if ! grep -qE "BUILD FAILURE|Compilation failure|Could not resolve dependencies" "$ATTEMPT2_LOG"; then
                echo "        -> [RESULT]: SUCCESS on attempt 2 after pom.xml fix!"
                ((FIXED++)) || true
            else
                echo "        -> [RESULT]: FAILED attempt 2 after patch."
                ((FAIL++)) || true
            fi
        else
            echo "        -> [RESULT]: LLM did not modify pom.xml."
            ((FAIL++)) || true
        fi
    else
        echo "        -> [RESULT]: SUCCESS (Compilation/Tests passed)"
        ((PASS++)) || true
    fi
done

echo ""
echo "======================================================"
echo "  RQ3 Build Summary:"
echo "    - Initially Passed: ${PASS}"
echo "    - Fixed by LLM:     ${FIXED}"
echo "    - Total Failed:     ${FAIL}"
echo "======================================================"