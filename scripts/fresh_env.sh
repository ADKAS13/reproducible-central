#!/usr/bin/env bash
# scripts/fresh_env.sh  (sourced by the pipeline scripts; RC_ROOT must be set)
#
# reset_run_env <buildspec>
#   - deletes the flavor folder's checkout (buildcache/) and old .buildcompare files
#   - wipes the Maven local repo (m2/) and restores only the plugin from m2-seed/
# so every run re-clones the sources and re-resolves every dependency and
# version range against the remote repositories.

M2_DIR="${RC_ROOT}/m2"
M2_SEED_DIR="${RC_ROOT}/m2-seed"
export SKIP_REMOTE_VERIFY=1

reset_run_env() {
    local spec="$1"
    local dir
    dir="$(dirname "$spec")"

    # first run only: restore the plugin
    if [ ! -d "$M2_DIR/repository" ]; then
        mkdir -p "$M2_DIR"
        cp -a "${M2_SEED_DIR}/." "${M2_DIR}/"
    fi

    # keep downloaded release jars; drop only cached version-resolution state
    find "$M2_DIR" \( -name 'maven-metadata-*.xml' \
        -o -name 'resolver-status.properties' \
        -o -name '*.lastUpdated' \) \
        ! -name 'maven-metadata-local.xml' -delete || return 1

    rm -rf "${dir}/buildcache" "${dir}"/*.buildcompare || return 1
}