#!/usr/bin/env bash

set -euo pipefail

# Check if repo name argument is provided
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <repo_name>"
    echo "Example: $0 automatalib"
    exit 1
fi

REPO_NAME="$1"
TARGET_DIR="repos/${REPO_NAME}"
LOG_DIR="logs/${REPO_NAME}"

# Validate target directory exists
if [ ! -d "${TARGET_DIR}" ]; then
    echo "[ERROR] Directory '${TARGET_DIR}' does not exist."
    exit 1
fi

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Find all .buildspec files recursively across subdirectories (e.g. base/, RQ1/, RQ2major/)
mapfile -t BUILDSPECS < <(find "${TARGET_DIR}" -type f -name "*.buildspec" | sort)

if [ "${#BUILDSPECS[@]}" -eq 0 ]; then
    echo "[WARN] No .buildspec files found in '${TARGET_DIR}'."
    exit 0
fi

echo "=========================================================="
echo " Found ${#BUILDSPECS[@]} buildspec(s) in '${TARGET_DIR}'"
echo "=========================================================="

# Track results
SUCCESSFUL_BUILDS=()
FAILED_BUILDS=()

# Loop through and run each buildspec script
for spec in "${BUILDSPECS[@]}"; do
    # Derive a clean log name from the spec filename (e.g., automatalibRQ1.buildspec -> automatalibRQ1.log)
    spec_filename=$(basename "${spec}")
    log_filename="${spec_filename%.buildspec}.log"
    log_file="${LOG_DIR}/${log_filename}"

    echo ""
    echo "----------------------------------------------------------"
    echo "[RUNNING] ${spec}"
    echo "[LOG]     ${log_file}"
    echo "----------------------------------------------------------"

    # Execute through rebuild.sh wrapper, redirecting stdout & stderr to the log file
    if ./rebuild.sh "${spec}" > "${log_file}" 2>&1; then
        # Verify if BUILD SUCCESS was actually printed inside the log output
        if grep -q "BUILD SUCCESS" "${log_file}"; then
            echo "[SUCCESS] ${spec} (BUILD SUCCESS achieved)"
            SUCCESSFUL_BUILDS+=("${spec} | Log: ${log_file}")
        else
            echo "[FAILED]  ${spec} (Finished with 0 exit code but missing 'BUILD SUCCESS')" >&2
            FAILED_BUILDS+=("${spec} | Log: ${log_file}")
        fi
    else
        echo "[FAILED]  ${spec} (Process returned non-zero exit code)" >&2
        FAILED_BUILDS+=("${spec} | Log: ${log_file}")
    fi
done

# Print final build summary
echo ""
echo "=========================================================="
echo "                    BUILD SUMMARY                         "
echo "=========================================================="

if [ "${#SUCCESSFUL_BUILDS[@]}" -gt 0 ]; then
    echo "SUCCESSFUL BUILDS (${#SUCCESSFUL_BUILDS[@]}):"
    for item in "${SUCCESSFUL_BUILDS[@]}"; do
        echo "  - ${item}"
    done
else
    echo "SUCCESSFUL BUILDS: None"
fi

echo ""

if [ "${#FAILED_BUILDS[@]}" -gt 0 ]; then
    echo "FAILED BUILDS (${#FAILED_BUILDS[@]}):"
    for item in "${FAILED_BUILDS[@]}"; do
        echo "  - ${item}"
    done
else
    echo "FAILED BUILDS: None"
fi

echo "=========================================================="

# Return non-zero exit code if any build failed
if [ "${#FAILED_BUILDS[@]}" -gt 0 ]; then
    exit 1
fi