#!/usr/bin/env bash
# run_base_pipeline.sh
#
# Runs rebuild.sh for every buildspec in the base<Flavor> folders, then collects
# dependency comparison results and RQ1-style equivalence/test stats into CSVs and console reports.
#
# Usage: ./run_base_pipeline.sh [Major|Minor|Patch] [pattern]
#
# Every buildspec lives in its own folder (repos/<repo>/base<Flavor>/<repo>Base<Flavor>.buildspec)
# e.g. repos/foo/baseMajor/fooBaseMajor.buildspec
# and runs with a fresh checkout and a fresh Maven local repo (see scripts/fresh_env.sh).

set -euo pipefail
export SKIP_REMOTE_VERIFY=1

# Flavor is normalised to a capitalised first letter (major -> Major) so that
# folder/file names are baseMajor / <repo>BaseMajor.buildspec.
RANGE_MODE_RAW="${1:-Minor}"
RANGE_MODE="${RANGE_MODE_RAW^}"          # Major | Minor | Patch
RANGE_MODE_LC="${RANGE_MODE,,}"          # major | minor | patch (for collectors expecting lowercase)
PATTERN="${2:-*Base${RANGE_MODE}.buildspec}"
FLAVOR_DIR="base${RANGE_MODE}"
RC_ROOT="$(pwd)"
REBUILD_SH="${RC_ROOT}/rebuild.sh"
COLLECT_RQ2_SCRIPT="$(dirname "$0")/scripts/collect_rq2_results.py"
COLLECT_RQ1_SCRIPT="$(dirname "$0")/scripts/collect_rq1_results.py"

OUTPUT_CSV="${RC_ROOT}/results/base_results_${RANGE_MODE_LC}.csv"
OUTPUT_RQ1_CSV="${RC_ROOT}/results/base_rq1_style_stats_${RANGE_MODE_LC}.csv"
LOG_DIR="${RC_ROOT}/base_logs_${RANGE_MODE_LC}"
STAGE_CSV="${RC_ROOT}/results/base_stage_status_${RANGE_MODE_LC}.csv"

# The buildspec runs three separate Maven invocations (range-test, range-compare, real build),
# so every log holds three "BUILD SUCCESS/FAILURE" lines. Stages are chained with &&, so the run
# stops at the first failing stage.
EXPECTED_STAGES=3
STAGE_NAMES=("" "range-test" "range-compare" "build")

# Per-log outcome: prints "successes failures compare_ran"
log_stats() {
    local log="$1" ok bad cmp
    ok=$(grep -aoE "BUILD SUCCESS" "$log" | wc -l || true)
    bad=$(grep -aoE "BUILD FAILURE" "$log" | wc -l || true)
    cmp=$(grep -ac "\[RANGE-COMPARE\] Dependency comparison for" "$log" || true)
    echo "${ok// /} ${bad// /} ${cmp// /}"
}

# shellcheck source=scripts/fresh_env.sh
. "$(dirname "$0")/scripts/fresh_env.sh"

mkdir -p "$LOG_DIR" "${RC_ROOT}/results"

echo "======================================================"
echo "  Base Pipeline — range mode: ${RANGE_MODE}"
echo "  Folder:  ${FLAVOR_DIR}"
echo "  Pattern: ${PATTERN}"
echo "  Output:  ${OUTPUT_CSV}"
echo "======================================================"

# Find all matching buildspecs, restricted to the base<Flavor> folders
mapfile -t BUILDSPECS < <(find "${RC_ROOT}/repos" -path "*/${FLAVOR_DIR}/*" -name "${PATTERN}" | sort)

if [ ${#BUILDSPECS[@]} -eq 0 ]; then
    echo "ERROR: No buildspecs found in */${FLAVOR_DIR}/ matching pattern: ${PATTERN}"
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
    read -r n_ok n_bad n_cmp < <(log_stats "$LOG_FILE")
    # Only a full run counts: the LAST verdict must be SUCCESS and every stage must have reported one.
    # (A run killed by the timeout after stage 1 would otherwise look like a success.)
    if [ "$verdict" = "BUILD SUCCESS" ] && [ "$n_ok" -ge "$EXPECTED_STAGES" ] && [ "$n_bad" -eq 0 ]; then
        echo "        -> SUCCESS (log: $LOG_FILE)"
        ((PASS++)) || true
        if [ $exit_code -ne 0 ]; then
            echo "        -> NOTE: rebuild.sh exited ${exit_code} despite BUILD SUCCESS (non-fatal post-build step)"
        fi
    else
        failed_stage=$(( n_ok + 1 ))
        [ "$failed_stage" -gt "$EXPECTED_STAGES" ] && failed_stage=$EXPECTED_STAGES
        echo "        -> FAILED at stage ${failed_stage}/${EXPECTED_STAGES} (${STAGE_NAMES[$failed_stage]})," \
             "comparison reports in log: ${n_cmp} (log: $LOG_FILE)"
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

# 0. Per-repo stage outcome, derived from ALL logs in LOG_DIR (so partial re-runs do not drop other repos).
#    Log names are <repo>_<repo>Base<Mode>.log, hence repo = first (len-1-len(Base<Mode>))/2 characters.
echo "repo,stages_ok,stages_failed,final_success,compare_ran,failed_stage" > "$STAGE_CSV"
bm="Base${RANGE_MODE}"
for log in "$LOG_DIR"/*.log; do
    [ -e "$log" ] || continue
    stem="$(basename "$log" .log)"
    rl=$(( (${#stem} - 1 - ${#bm}) / 2 ))
    repo="${stem:0:$rl}"
    read -r n_ok n_bad n_cmp < <(log_stats "$log")
    last=$(grep -aoE "BUILD (SUCCESS|FAILURE)" "$log" | tail -n 1 || true)
    final=False; [ "$last" = "BUILD SUCCESS" ] && [ "$n_ok" -ge "$EXPECTED_STAGES" ] && [ "$n_bad" -eq 0 ] && final=True
    ran=False; [ "$n_cmp" -gt 0 ] && ran=True
    fs=0; [ "$final" = False ] && fs=$(( n_ok + 1 > EXPECTED_STAGES ? EXPECTED_STAGES : n_ok + 1 ))
    echo "${repo},${n_ok},${n_bad},${final},${ran},${fs}" >> "$STAGE_CSV"
done
echo "[STAGES] Stage outcomes written to ${STAGE_CSV}"
echo ""

# 1. Collect Dependency Change Summary
echo "[COLLECT] Running Dependency Change Analysis (base${RANGE_MODE})..."
python3 "${COLLECT_RQ2_SCRIPT}" \
    --root "${RC_ROOT}" \
    --range "${RANGE_MODE_LC}" \
    --log-dir "${LOG_DIR}" \
    --output "${OUTPUT_CSV}" \
    --mode "base" \
    --lag
echo ""

# 2. Collect RQ1-style Build, Test, and Binary Equivalence Stats
echo "[COLLECT] Scanning for comparison reports and test results..."
python3 "${COLLECT_RQ1_SCRIPT}" \
    --root "${RC_ROOT}" \
    --output "${OUTPUT_RQ1_CSV}" \
    --log-dir "${LOG_DIR}" \
    --flavor "${FLAVOR_DIR}"

echo ""


echo "Done."
echo "  - Dependency Results:       ${OUTPUT_CSV}"
echo "  - Equivalence & Test Stats: ${OUTPUT_RQ1_CSV}"
echo "  - Stage outcomes:           ${STAGE_CSV}"