#!/usr/bin/env bash
# run_rq1_pipeline.sh
#
# Runs rebuild.sh for every *RQ1.buildspec file, collects results into CSV,
# and prints a summary matching the RQ2 pipeline style.
#
# Usage:
#   ./run_rq1_pipeline.sh [buildspec_pattern]
#
# Examples:
#   ./run_rq1_pipeline.sh                  # all *RQ1.buildspec files
#   ./run_rq1_pipeline.sh "*RQ1.buildspec" # explicit pattern
#
# Requirements:
#   - Run from the reproducible-central root directory
#   - counter-maven-plugin installed in reproducible-central/m2
#   - Python 3.9+ for collect_rq1_results.py

set -uo pipefail

PATTERN="${1:-*RQ1.buildspec}"
RC_ROOT="$(pwd)"
REBUILD_SH="${RC_ROOT}/rebuild.sh"
COLLECT_SCRIPT="$(dirname "$0")/scripts/collect_rq1_results.py"
OUTPUT_CSV="${RC_ROOT}/results/rq1_results.csv"
LOG_DIR="${RC_ROOT}/rq1_logs"

mkdir -p "$LOG_DIR"

echo "======================================================"
echo "  RQ1 Pipeline — pinned flattening, equivalence check"
echo "  Pattern: ${PATTERN}"
echo "  Output:  ${OUTPUT_CSV}"
echo "======================================================"

mapfile -t BUILDSPECS < <(find "${RC_ROOT}" -name "${PATTERN}" | sort)

if [ ${#BUILDSPECS[@]} -eq 0 ]; then
    echo "ERROR: No buildspecs found matching pattern: ${PATTERN}"
    exit 1
fi

echo "Found ${#BUILDSPECS[@]} buildspec(s):"
for spec in "${BUILDSPECS[@]}"; do
    echo "  - $(basename "$(dirname "$spec")")/$(basename "$spec")"
done
echo ""

PASS=0
FAIL=0
FAIL_LIST=()

for spec in "${BUILDSPECS[@]}"; do
    REPO=$(basename "$(dirname "$spec")")
    SPEC_NAME=$(basename "$spec")
    LOG_FILE="${LOG_DIR}/${REPO}_${SPEC_NAME%.buildspec}.log"

    echo "[BUILD] ${REPO}/${SPEC_NAME}"

    if bash "${REBUILD_SH}" "$spec" > "$LOG_FILE" 2>&1; then
        echo "        -> SUCCESS (log: $LOG_FILE)"
        ((PASS++)) || true
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

echo "[COLLECT] Scanning for comparison reports and test results..."
python3 "${COLLECT_SCRIPT}" \
    --root "${RC_ROOT}" \
    --output "${OUTPUT_CSV}" \
    --log-dir "${LOG_DIR}"

echo ""
echo "Done. Results: ${OUTPUT_CSV}"