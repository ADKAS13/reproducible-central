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

# Validate target directory exists
if [ ! -d "${TARGET_DIR}" ]; then
    echo "[ERROR] Directory '${TARGET_DIR}' does not exist."
    exit 1
fi

# Find all .buildspec files (sorted alphabetically)
mapfile -t BUILDSPECS < <(find "${TARGET_DIR}" -maxdepth 1 -type f -name "*.buildspec" | sort)

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
    echo ""
    echo "----------------------------------------------------------"
    echo "[RUNNING] ${spec}"
    echo "----------------------------------------------------------"
    
    # Execute through rebuild.sh wrapper
    if ./rebuild.sh "${spec}"; then
        echo "[SUCCESS] ${spec}"
        SUCCESSFUL_BUILDS+=("${spec}")
    else
        echo "[FAILED] ${spec}" >&2
        FAILED_BUILDS+=("${spec}")
    fi
done

# Print final build summary
echo ""
echo "=========================================================="
echo "                    BUILD SUMMARY                         "
echo "=========================================================="

if [ "${#SUCCESSFUL_BUILDS[@]}" -gt 0 ]; then
    echo "SUCCESSFUL BUILDS (${#SUCCESSFUL_BUILDS[@]}):"
    for spec in "${SUCCESSFUL_BUILDS[@]}"; do
        echo "  - ${spec}"
    done
else
    echo "SUCCESSFUL BUILDS: None"
fi

echo ""

if [ "${#FAILED_BUILDS[@]}" -gt 0 ]; then
    echo "FAILED BUILDS (${#FAILED_BUILDS[@]}):"
    for spec in "${FAILED_BUILDS[@]}"; do
        echo "  - ${spec}"
    done
else
    echo "FAILED BUILDS: None"
fi

echo "=========================================================="

# Return non-zero exit code if any build failed
if [ "${#FAILED_BUILDS[@]}" -gt 0 ]; then
    exit 1
fi