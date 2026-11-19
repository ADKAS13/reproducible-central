#!/usr/bin/env python3
"""
collect_base_results.py — Collect dependency comparison results from base range builds.

After running rebuild.sh for base range buildspecs, this script scans the buildcache 
directories for dependency-comparison-report.txt files and aggregates them into a CSV.

Output CSV columns:
    repo, module, range_mode, pinned, upgraded, downgraded, added, removed,
    scope_changed, total_before, total_after, build_success, versions_jumped, lag metrics...
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, fields, asdict
from typing import Optional

import technical_lag  # lives next to this script

from collect_rq1_results import find_flavor_log, log_build_success

NO_REPORT = "<no-report>"


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
    build_success: bool = False

    # Number of intermediate versions jumped/updated across by upgraded dependencies
    versions_jumped: int = 0

    # technical lag, filled in when run with --lag (see technical_lag.py)
    lag_deps: int = 0
    lag_days_deps: int = 0
    lag_days_before: float = 0.0
    lag_days_after: float = 0.0
    lag_days_reduction: float = 0.0
    behind_before: int = 0
    behind_after: int = 0
    behind_reduction: int = 0
    stale_major_before: int = 0
    stale_minor_before: int = 0
    stale_patch_before: int = 0
    stale_major_after: int = 0
    stale_minor_after: int = 0
    stale_patch_after: int = 0
    lag_unknown: int = 0
    not_at_policy_latest: int = 0

    @property
    def total_changed(self):
        return self.upgraded + self.downgraded + self.added + self.removed + self.scope_changed


def flavor_for(range_mode: str) -> str:
    return f"base{range_mode.capitalize()}"   # major -> baseMajor


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


def collect_from_buildcache(buildcache: Path, repo: str, range_mode: str,
                            build_success: bool) -> list[ModuleResult]:
    """Scan a buildcache directory for all comparison reports."""
    results = []
    for report_path in sorted(buildcache.rglob("dependency-comparison-report.txt")):
        result = parse_report(report_path, repo, range_mode)
        if result:
            result.build_success = build_success
            results.append(result)

    if not results:
        print(f"[WARN] {repo}: no comparison reports in {buildcache} — recording a "
              f"'{NO_REPORT}' row (build={'PASS' if build_success else 'FAIL'})", file=sys.stderr)
        results.append(ModuleResult(repo=repo, module=NO_REPORT, range_mode=range_mode,
                                    build_success=build_success))
    return results


def collect_from_root(root: Path, range_mode: str, log_dir: Path) -> list[ModuleResult]:
    """
    Scan all subdirectories of reproducible-central root for base buildcaches.
    Expects structure: repos/<repo>/base<range>/buildcache/
    """
    results = []
    expected_flavor = flavor_for(range_mode)
    for buildcache in sorted(root.rglob("buildcache")):
        if not buildcache.is_dir():
            continue
        try:
            relative = buildcache.relative_to(root / "repos")
        except ValueError:
            continue
        if len(relative.parts) != 3:  # <repo>/base<range>/buildcache
            continue
        repo, flavor = relative.parts[0], relative.parts[1]
        if flavor != expected_flavor:
            continue

        log = find_flavor_log(log_dir, repo, expected_flavor)
        if log is None:
            print(f"[SKIP] {repo}: no {expected_flavor} log in {log_dir} (stale buildcache?)", file=sys.stderr)
            continue

        results.extend(collect_from_buildcache(buildcache, repo, range_mode, log_build_success(log)))
    return results


def run_buildspec(rebuild_sh: Path, buildspec: Path, log_dir: Path, dry_run: bool = False) -> bool:
    """Invoke rebuild.sh for a single base buildspec, saving output to log_dir."""
    repo = buildspec.resolve().parent.parent.name
    log_path = log_dir / f"{repo}_{buildspec.stem}.log"
    cmd = [str(rebuild_sh), str(buildspec)]
    print(f"[RUN] {' '.join(cmd)}  (log: {log_path})")
    if dry_run:
        return True

    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        proc.wait()
    return proc.returncode == 0


def print_summary(results: list[ModuleResult], range_mode: str):
    """Print an aggregated summary table to stdout."""
    if not results:
        print("No results found.")
        return

    by_repo: dict[str, list[ModuleResult]] = {}
    for r in results:
        by_repo.setdefault(r.repo, []).append(r)

    print(f"\n{'='*88}")
    print(f"  Base Ranges Dependency Change Summary — range mode: {range_mode}")
    print(f"{'='*88}")
    print(f"{'Repo':<26} {'Build':>6} {'Mods':>5} {'Pinned':>7} {'Upgr':>6} {'Jumped':>7} {'Downgr':>7} {'Added':>6} {'Removed':>8}")
    print(f"{'-'*88}")

    builds_ok = 0

    for repo, repo_results in sorted(by_repo.items()):
        mods      = sum(1 for r in repo_results if r.module != NO_REPORT)
        build_ok  = repo_results[0].build_success
        pinned    = sum(r.pinned for r in repo_results)
        upgraded  = sum(r.upgraded for r in repo_results)
        jumped    = sum(r.versions_jumped for r in repo_results)
        downgraded= sum(r.downgraded for r in repo_results)
        added     = sum(r.added for r in repo_results)
        removed   = sum(r.removed for r in repo_results)

        print(f"{repo:<26} {'PASS' if build_ok else 'FAIL':>6} {mods:>5} {pinned:>7} {upgraded:>6} "
              f"{jumped:>7} {downgraded:>7} {added:>6} {removed:>8}")

        builds_ok += 1 if build_ok else 0

    print(f"{'-'*88}")
    print(f"Summary totals collected successfully.")
    print(f"{'='*88}\n")


def write_csv(results: list[ModuleResult], output: Path):
    """Write results to CSV."""
    if not results:
        print("No results to write.")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(ModuleResult)]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    print(f"Results written to {output} ({len(results)} module rows)")


def main():
    parser = argparse.ArgumentParser(description="Collect base range dependency comparison results.")

    parser.add_argument("--root", type=Path,
                        help="Root of reproducible-central checkout (scans all base buildcaches)")
    parser.add_argument("--buildcache", type=Path,
                        help="Path to a single buildcache directory")
    parser.add_argument("--repo", type=str, default="unknown",
                        help="Repo name (used when --buildcache is specified)")
    parser.add_argument("--range", type=str, default="pinned",
                        choices=["pinned", "patch", "minor", "major"],
                        help="Version range mode used in the base build (selects flavor base<range>)")
    parser.add_argument("--log-dir", type=Path, default=None,
                        help="Directory with the rebuild.sh logs (default: <root>/base_logs).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output CSV file path (default: base_ranges_results_<range>.csv)")
    parser.add_argument("--buildspecs", type=Path, nargs="*",
                        help="Run rebuild.sh for these buildspecs before collecting")
    parser.add_argument("--rebuild-sh", type=Path, default=None,
                        help="Path to rebuild.sh (required if --buildspecs is used)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rebuild commands without running them")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary table but don't write CSV")

    parser.add_argument("--lag", action="store_true",
                        help="Also measure technical lag (version and time) before vs after the update")
    parser.add_argument("--lag-cache", type=Path, default=Path("results/.lag_cache.json"),
                        help="Frozen Maven Central snapshot used as 'latest'")
    parser.add_argument("--lag-refresh", action="store_true",
                        help="Refetch the release lists even if cached")
    parser.add_argument("--lag-scopes", type=str, default=None,
                        help="Comma separated scopes to include, e.g. compile,runtime")
    parser.add_argument("--lag-workers", type=int, default=4,
                        help="Parallel requests to Maven Central (default 4)")

    args = parser.parse_args()

    log_dir = args.log_dir or ((args.root or Path.cwd()) / "base_logs")

    # Optionally run rebuilds first
    if args.buildspecs:
        if not args.rebuild_sh or not args.rebuild_sh.exists():
            print("ERROR: --rebuild-sh must point to a valid rebuild.sh when using --buildspecs", file=sys.stderr)
            sys.exit(1)
        for spec in args.buildspecs:
            success = run_buildspec(args.rebuild_sh, spec, log_dir, dry_run=args.dry_run)
            if not success:
                print(f"[WARN] Build failed for {spec}", file=sys.stderr)

    # Collect results
    results: list[ModuleResult] = []
    expected_flavor = flavor_for(args.range)

    if args.buildcache:
        log = find_flavor_log(log_dir, args.repo, expected_flavor)
        if log is None:
            print(f"[WARN] No {expected_flavor} log for '{args.repo}' in {log_dir} — build_success will be False.",
                  file=sys.stderr)
        build_success = log is not None and log_build_success(log)
        results = collect_from_buildcache(args.buildcache, args.repo, args.range, build_success)
    elif args.root:
        results = collect_from_root(args.root, args.range, log_dir)
    else:
        print("ERROR: specify --root or --buildcache", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No results found. Have you run the base builds yet (and is --log-dir correct)?")
        sys.exit(0)

    default_output = Path(f"base_ranges_results_{args.range}.csv")
    out = args.output or default_output

    if args.lag:
        technical_lag.enrich(results, args.range, args.lag_cache, refresh=args.lag_refresh,
                             workers=args.lag_workers, root=getattr(args, "root", None), buildcache=getattr(args, "buildcache", None),
                             scopes=set(args.lag_scopes.split(",")) if args.lag_scopes else None,
                             detail_path=out.with_name(out.stem + "_lag_detail.csv"))

    # Print summary
    print_summary(results, args.range)

    # Write CSV
    if not args.summary_only:
        write_csv(results, out)


if __name__ == "__main__":
    main()