#!/usr/bin/env bash
# scripts/make_m2_seed.sh
#
# Run once from the reproducible-central root, after counter-maven-plugin has
# been installed into m2/. Copies ONLY the plugin into m2-seed/, which
# fresh_env.sh restores into a wiped m2/ before every run.
# Re-run it whenever you rebuild/reinstall the plugin.

set -euo pipefail

src="$(find m2 -type d -path '*/com/baeldung/counter-maven-plugin' -print -quit)"
[ -n "$src" ] || { echo "ERROR: counter-maven-plugin not found under m2/" >&2; exit 1; }

rel="${src#m2/}"
rm -rf m2-seed
mkdir -p "m2-seed/$(dirname "$rel")"
cp -a "$src" "m2-seed/$(dirname "$rel")/"
echo "Seeded: m2-seed/${rel}"