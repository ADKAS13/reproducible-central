#!/usr/bin/env bash
# run_rq2_pipeline.sh
#
# Runs rebuild.sh for every buildspec matching a pattern, then collects
# dependency comparison results into a CSV.
#
# Usage:
#   ./run_rq2_pipeline.sh <range_mode> [buildspec_pattern]
#
# Examples:
#   ./run_rq2_pipeline.sh minor                        # all *RQ2minor.buildspec files
#   ./run_rq2_pipeline.sh major "*RQ2major.buildspec"  # explicit pattern
#   ./run_rq2_pipeline.sh pinned "*RQ2pinned.buildspec"
#
# Requirements:
#   - Run from the reproducible-central root directory
#   - counter-maven-plugin must be installed in local .m2
#   - Python 3.9+ for collect_results.py

set -euo pipefail

RANGE_MODE="${1:-minor}"
PATTERN="${2:-*RQ2${RANGE_MODE}.buildspec}"
RC_ROOT="$(pwd)"
REBUILD_SH="${RC_ROOT}/rebuild.sh"
COLLECT_SCRIPT="$(dirname "$0")/collect_results.py"
OUTPUT_CSV="${RC_ROOT}/rq2_results_${RANGE_MODE}.csv"
LOG_DIR="${RC_ROOT}/rq2_logs_${RANGE_MODE}"

mkdir -p "$LOG_DIR"

echo "======================================================"
echo "  RQ2 Pipeline — range mode: ${RANGE_MODE}"
echo "  Pattern: ${PATTERN}"
echo "  Output:  ${OUTPUT_CSV}"
echo "======================================================"

# Find all matching buildspecs
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

# Run each buildspec
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

# Collect results into CSV
echo "[COLLECT] Scanning for comparison reports..."
python3 "${COLLECT_SCRIPT}" \
    --root "${RC_ROOT}" \
    --range "${RANGE_MODE}" \
    --output "${OUTPUT_CSV}"

echo ""
echo "Done. Results: ${OUTPUT_CSV}"