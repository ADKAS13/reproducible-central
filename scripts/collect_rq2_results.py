#!/usr/bin/env python3
"""
collect_results.py — Collect dependency comparison results from reproducible-central builds.

After running rebuild.sh for one or more buildspecs that use the counter-maven-plugin,
this script scans the buildcache directories for dependency-comparison-report.txt files
and aggregates them into a CSV.

Usage:
    # Collect results for a single repo after rebuild
    python collect_results.py --buildcache ~/reproducible-central/automatalib/buildcache \
                               --repo automatalib --range minor

    # Collect results across ALL repos
    python collect_results.py --root ~/reproducible-central --range major

    # Collect and compare two ranges
    python collect_results.py --root ~/reproducible-central --range minor --output results_minor.csv
    python collect_results.py --root ~/reproducible-central --range major --output results_major.csv

Output CSV columns:
    repo, module, range_mode, pinned, upgraded, downgraded, added, removed,
    scope_changed, total_before, total_after, build_success

For the pipeline mode (--buildspecs), this script can also invoke rebuild.sh
for each buildspec and collect results in one go.
"""

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, fields, asdict
from typing import Optional


@dataclass
class ModuleResult:
    repo: str
    module: str
    range_mode: str
    pinned: int = 0
    upgraded: int = 0
    downgraded: int = 0
    added: int = 0
    removed: int = 0
    scope_changed: int = 0
    total_before: int = 0
    total_after: int = 0
    build_success: bool = True

    @property
    def total_changed(self):
        return self.upgraded + self.downgraded + self.added + self.removed + self.scope_changed


def parse_report(report_path: Path, repo: str, range_mode: str) -> Optional[ModuleResult]:
    """Parse a single dependency-comparison-report.txt into a ModuleResult."""
    result = ModuleResult(repo=repo, module="", range_mode=range_mode)
    try:
        with open(report_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("MODULE="):
                    result.module = line.split("=", 1)[1]
                elif line.startswith("PINNED="):
                    result.pinned = int(line.split("=", 1)[1])
                elif line.startswith("UPGRADED="):
                    result.upgraded = int(line.split("=", 1)[1])
                elif line.startswith("DOWNGRADED="):
                    result.downgraded = int(line.split("=", 1)[1])
                elif line.startswith("ADDED="):
                    result.added = int(line.split("=", 1)[1])
                elif line.startswith("REMOVED="):
                    result.removed = int(line.split("=", 1)[1])
                elif line.startswith("SCOPE_CHANGED="):
                    result.scope_changed = int(line.split("=", 1)[1])

        result.total_before = result.pinned + result.upgraded + result.downgraded + result.removed + result.scope_changed
        result.total_after  = result.pinned + result.upgraded + result.downgraded + result.added  + result.scope_changed
        return result
    except Exception as e:
        print(f"[WARN] Failed to parse {report_path}: {e}", file=sys.stderr)
        return None


def collect_from_buildcache(buildcache: Path, repo: str, range_mode: str) -> list[ModuleResult]:
    """Scan a buildcache directory for all comparison reports."""
    results = []
    for report_path in sorted(buildcache.rglob("dependency-comparison-report.txt")):
        result = parse_report(report_path, repo, range_mode)
        if result:
            results.append(result)
    return results


def collect_from_root(root: Path, range_mode: str) -> list[ModuleResult]:
    """
    Scan all subdirectories of a reproducible-central root for buildcaches.
    Expects structure: repos/<repo>/<flavor>/buildcache/
    """
    results = []
    for buildcache in sorted(root.rglob("buildcache")):
        if not buildcache.is_dir():
            continue
        # Expect repos/<repo>/<flavor>/buildcache — anything shallower is stale/misplaced
        try:
            relative = buildcache.relative_to(root / "repos")
        except ValueError:
            continue
        if len(relative.parts) != 3:  # <repo>/<flavor>/buildcache
            print(f"[SKIP] Unexpected buildcache depth: {buildcache}", file=sys.stderr)
            continue
        repo, flavor = relative.parts[0], relative.parts[1]
        expected_flavor = f"RQ2{args.range}"
        if flavor != expected_flavor:
          continue

        
        repo_results = collect_from_buildcache(buildcache, repo, range_mode)
        results.extend(repo_results)
    return results


def run_buildspec(rebuild_sh: Path, buildspec: Path, dry_run: bool = False) -> bool:
    """Invoke rebuild.sh for a single buildspec. Returns True if build succeeded."""
    cmd = [str(rebuild_sh), str(buildspec)]
    print(f"[RUN] {' '.join(cmd)}")
    if dry_run:
        return True
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def print_summary(results: list[ModuleResult], range_mode: str):
    """Print an aggregated summary table to stdout."""
    if not results:
        print("No results found.")
        return

    # Group by repo
    by_repo: dict[str, list[ModuleResult]] = {}
    for r in results:
        by_repo.setdefault(r.repo, []).append(r)

    print(f"\n{'='*70}")
    print(f"  Dependency Change Summary — range mode: {range_mode}")
    print(f"{'='*70}")
    print(f"{'Repo':<30} {'Mods':>5} {'Pinned':>7} {'Upgr':>6} {'Downgr':>7} {'Added':>6} {'Removed':>8} {'ScopeCh':>8}")
    print(f"{'-'*70}")

    total_mods = total_pinned = total_upgraded = total_downgraded = 0
    total_added = total_removed = total_scope = 0

    for repo, repo_results in sorted(by_repo.items()):
        mods      = len(repo_results)
        pinned    = sum(r.pinned for r in repo_results)
        upgraded  = sum(r.upgraded for r in repo_results)
        downgraded= sum(r.downgraded for r in repo_results)
        added     = sum(r.added for r in repo_results)
        removed   = sum(r.removed for r in repo_results)
        scope     = sum(r.scope_changed for r in repo_results)

        print(f"{repo:<30} {mods:>5} {pinned:>7} {upgraded:>6} {downgraded:>7} {added:>6} {removed:>8} {scope:>8}")

        total_mods      += mods
        total_pinned    += pinned
        total_upgraded  += upgraded
        total_downgraded+= downgraded
        total_added     += added
        total_removed   += removed
        total_scope     += scope

    print(f"{'-'*70}")
    print(f"{'TOTAL':<30} {total_mods:>5} {total_pinned:>7} {total_upgraded:>6} {total_downgraded:>7} {total_added:>6} {total_removed:>8} {total_scope:>8}")
    print(f"{'='*70}\n")


def write_csv(results: list[ModuleResult], output: Path):
    """Write results to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [f.name for f in fields(ModuleResult)]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    print(f"Results written to {output} ({len(results)} module rows)")


def main():
    parser = argparse.ArgumentParser(description="Collect dependency comparison results from reproducible-central builds.")

    parser.add_argument("--root", type=Path,
                        help="Root of reproducible-central checkout (scans all buildcaches)")
    parser.add_argument("--buildcache", type=Path,
                        help="Path to a single buildcache directory")
    parser.add_argument("--repo", type=str, default="unknown",
                        help="Repo name (used when --buildcache is specified)")
    parser.add_argument("--range", type=str, default="pinned",
                        choices=["pinned", "patch", "minor", "major"],
                        help="Version range mode used in the build (for labelling)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output CSV file path (default: results_<range>.csv)")
    parser.add_argument("--buildspecs", type=Path, nargs="*",
                        help="Run rebuild.sh for these buildspecs before collecting")
    parser.add_argument("--rebuild-sh", type=Path, default=None,
                        help="Path to rebuild.sh (required if --buildspecs is used)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rebuild commands without running them")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary table but don't write CSV")

    args = parser.parse_args()

    # Optionally run rebuilds first
    if args.buildspecs:
        if not args.rebuild_sh or not args.rebuild_sh.exists():
            print("ERROR: --rebuild-sh must point to a valid rebuild.sh when using --buildspecs", file=sys.stderr)
            sys.exit(1)
        for spec in args.buildspecs:
            success = run_buildspec(args.rebuild_sh, spec, dry_run=args.dry_run)
            if not success:
                print(f"[WARN] Build failed for {spec}", file=sys.stderr)

    # Collect results
    results: list[ModuleResult] = []

    if args.buildcache:
        results = collect_from_buildcache(args.buildcache, args.repo, args.range)
    elif args.root:
        results = collect_from_root(args.root, args.range)
    else:
        print("ERROR: specify --root or --buildcache", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No dependency-comparison-report.txt files found. Have you run the builds yet?")
        sys.exit(0)

    # Print summary
    print_summary(results, args.range)

    # Write CSV
    if not args.summary_only:
        output = args.output or Path(f"results_{args.range}.csv")
        write_csv(results, output)


if __name__ == "__main__":
    main()