#!/usr/bin/env bash
# run_rq2_pipeline.sh
#
# Runs rebuild.sh for every buildspec matching a pattern, then collects
# dependency comparison results and RQ1-style equivalence/test stats into CSVs and console reports.
#
# Every buildspec lives in its own folder (repos/<repo>/RQ2<mode>/<repo>RQ2<mode>.buildspec)
# and runs with a fresh checkout and a fresh Maven local repo (see scripts/fresh_env.sh).

set -euo pipefail
export SKIP_REMOTE_VERIFY=1

RANGE_MODE="${1:-minor}"
PATTERN="${2:-*RQ2${RANGE_MODE}.buildspec}"
RC_ROOT="$(pwd)"
REBUILD_SH="${RC_ROOT}/rebuild.sh"
COLLECT_RQ2_SCRIPT="$(dirname "$0")/scripts/collect_rq2_results.py"
COLLECT_RQ1_SCRIPT="$(dirname "$0")/scripts/collect_rq1_results.py"

OUTPUT_CSV="${RC_ROOT}/results/rq2_results_${RANGE_MODE}.csv"
OUTPUT_RQ1_CSV="${RC_ROOT}/results/rq1_style_stats_${RANGE_MODE}.csv"
LOG_DIR="${RC_ROOT}/rq2_logs_${RANGE_MODE}"

# shellcheck source=scripts/fresh_env.sh
. "$(dirname "$0")/scripts/fresh_env.sh"

mkdir -p "$LOG_DIR" "${RC_ROOT}/results"

echo "======================================================"
echo "  RQ2 Pipeline — range mode: ${RANGE_MODE}"
echo "  Pattern: ${PATTERN}"
echo "  Output:  ${OUTPUT_CSV}"
echo "======================================================"

# Find all matching buildspecs
mapfile -t BUILDSPECS < <(find "${RC_ROOT}/repos" -name "${PATTERN}" | sort)

if [ ${#BUILDSPECS[@]} -eq 0 ]; then
    echo "ERROR: No buildspecs found matching pattern: ${PATTERN}"
    exit 1
fi

# repo name = grandparent folder (repos/<repo>/<flavor>/<file>.buildspec)
repo_of() { basename "$(dirname "$(dirname "$1")")"; }

echo "Found ${#BUILDSPECS[@]} buildspec(s):"
for spec in "${BUILDSPECS[@]}"; do
    echo "  - $(repo_of "$spec")/$(basename "$spec")"
done
echo ""

# Run each buildspec
PASS=0
FAIL=0
FAIL_LIST=()

for spec in "${BUILDSPECS[@]}"; do
    REPO="$(repo_of "$spec")"
    SPEC_NAME=$(basename "$spec")
    LOG_FILE="${LOG_DIR}/${REPO}_${SPEC_NAME%.buildspec}.log"

    echo "[BUILD] ${REPO}/${SPEC_NAME}"

    rm -f "$LOG_FILE"    # never reuse a log from an earlier invocation

    if ! reset_run_env "$spec"; then
        echo "        -> RESET FAILED, skipping"
        echo "reset_run_env failed; no build was run" > "$LOG_FILE"
        ((FAIL++)) || true
        FAIL_LIST+=("${REPO}/${SPEC_NAME}")
        continue
    fi

    exit_code=0

    timeout --foreground 2h bash "${REBUILD_SH}" "$spec" > "$LOG_FILE" 2>&1 || exit_code=$?
    docker rm -f rebuild-central >/dev/null 2>&1 || true

    verdict=$(grep -aoE "BUILD (SUCCESS|FAILURE)" "$LOG_FILE" | tail -n 1 || true)
    if [ "$verdict" = "BUILD SUCCESS" ]; then
        echo "        -> SUCCESS (log: $LOG_FILE)"
        ((PASS++)) || true
        if [ $exit_code -ne 0 ]; then
            echo "        -> NOTE: rebuild.sh exited ${exit_code} despite BUILD SUCCESS (non-fatal post-build step)"
        fi
    else
        echo "        -> FAILED  (log: $LOG_FILE)"
        ((FAIL++)) || true
        FAIL_LIST+=("${REPO}/${SPEC_NAME}")
    fi
done

echo ""
echo "======================================================"
echo "  Build results: ${PASS} passed, ${FAIL} failed"
if [ ${#FAIL_LIST[@]} -gt 0 ]; then
    echo "  Failed:"
    for f in "${FAIL_LIST[@]}"; do
        echo "    - $f"
    done
fi
echo "======================================================"
echo ""

# 1. Collect RQ2 Dependency Change Summary
echo "[COLLECT] Running RQ2 Dependency Change Analysis..."
python3 "${COLLECT_RQ2_SCRIPT}" \
    --root "${RC_ROOT}" \
    --range "${RANGE_MODE}" \
    --log-dir "${LOG_DIR}" \
    --output "${OUTPUT_CSV}"

echo ""

# 2. Collect RQ1-style Build, Test, and Binary Equivalence Stats
echo "[COLLECT] Scanning for comparison reports and test results..."
python3 "${COLLECT_RQ1_SCRIPT}" \
    --root "${RC_ROOT}" \
    --output "${OUTPUT_RQ1_CSV}" \
    --log-dir "${LOG_DIR}" \
    --flavor "RQ2${RANGE_MODE}"

echo ""
echo "Done."
echo "  - RQ2 Dependency Results: ${OUTPUT_CSV}"
echo "  - Equivalence & Test Stats: ${OUTPUT_RQ1_CSV}"