#!/usr/bin/env python3
"""
collect_results.py — Unified dependency comparison result collector for base and RQ2 builds.
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
    build_time_s: float = 0.0
    versions_jumped: int = 0

    # Technical lag metrics
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

def norm_mode(mode):
    return "base" if mode.lower() in ("base", "base_range") else "rq2"

def flavor_for(mode, range_mode):
    return f"base{range_mode.capitalize()}" if norm_mode(mode) == "base" else f"RQ2{range_mode}"


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


def collect_from_root(root: Path, mode: str, range_mode: str, log_dir: Path) -> list[ModuleResult]:
    results = []
    expected_flavor = flavor_for(mode, range_mode)
    stages = 3 if mode.lower() == "base" else 1   # needs log_build_success(log, stages) from the earlier patch

    for flavor_dir in sorted((root / "repos").glob(f"*/{expected_flavor}")):
        if not flavor_dir.is_dir():
            continue
        repo = flavor_dir.parent.name

        log = find_flavor_log(log_dir, repo, expected_flavor)
        if log is None:
            print(f"[SKIP] {repo}: no {expected_flavor} log in {log_dir} (stale checkout?)", file=sys.stderr)
            continue
        build_success = log_build_success(log, stages)
        print(f"[LOG] {repo} -> {log.name if log else None} success={build_success}", file=sys.stderr)
        _, seconds = technical_lag.parse_maven_log(log)
        build_time = float(seconds) if seconds is not None else 0.0

        repo_results = []
        for rp in sorted(flavor_dir.rglob("dependency-comparison-report.txt")):
            res = parse_report(rp, repo, range_mode)
            if res:
                res.build_success = build_success
                res.build_time_s = build_time
                repo_results.append(res)

        if not repo_results:
            print(f"[WARN] {repo}: no comparison reports under {flavor_dir} — recording a '{NO_REPORT}' row "
                  f"(build={'PASS' if build_success else 'FAIL'})", file=sys.stderr)
            repo_results.append(ModuleResult(repo=repo, module=NO_REPORT, range_mode=range_mode,
                                             build_success=build_success, build_time_s=build_time))
        results.extend(repo_results)
    return results


def run_buildspec(rebuild_sh: Path, buildspec: Path, log_dir: Path, dry_run: bool = False) -> bool:
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


def print_summary(results: list[ModuleResult], mode: str, range_mode: str):
    if not results:
        print("No results found.")
        return

    by_repo: dict[str, list[ModuleResult]] = {}
    for r in results:
        by_repo.setdefault(r.repo, []).append(r)

    print(f"\n{'='*95}")
    print(f"  {mode.upper()} Dependency Change Summary — range mode: {range_mode}")
    print(f"{'='*95}")
    print(f"{'Repo':<26} {'Build':>6} {'Time(s)':>8} {'Mods':>5} {'Pinned':>7} {'Upgr':>6} {'Jumped':>8} {'Downgr':>7} {'Added':>6} {'Removed':>8}")
    print(f"{'-'*95}")

    builds_ok = 0
    total_mods = total_pinned = total_upgraded = total_jumped = total_downgraded = total_added = total_removed = 0

    for repo, repo_results in sorted(by_repo.items()):
        mods      = sum(1 for r in repo_results if r.module != NO_REPORT)
        build_ok  = repo_results[0].build_success
        build_time= repo_results[0].build_time_s
        pinned    = sum(r.pinned for r in repo_results)
        upgraded  = sum(r.upgraded for r in repo_results)
        jumped    = sum(r.versions_jumped for r in repo_results)
        downgraded= sum(r.downgraded for r in repo_results)
        added     = sum(r.added for r in repo_results)
        removed   = sum(r.removed for r in repo_results)

        print(f"{repo:<26} {'PASS' if build_ok else 'FAIL':>6} {build_time:>8.1f} {mods:>5} {pinned:>7} {upgraded:>6} "
              f"{jumped:>8} {downgraded:>7} {added:>6} {removed:>8}")

        builds_ok       += 1 if build_ok else 0
        total_mods      += mods
        total_pinned    += pinned
        total_upgraded  += upgraded
        total_jumped    += jumped
        total_downgraded+= downgraded
        total_added     += added
        total_removed   += removed

    print(f"{'-'*95}")
    print(f"{'TOTAL':<26} {builds_ok:>3}/{len(by_repo):<2} {'-':>8} {total_mods:>5} {total_pinned:>7} {total_upgraded:>6} "
          f"{total_jumped:>8} {total_downgraded:>7} {total_added:>6} {total_removed:>8}")
    print(f"{'='*95}\n")


def write_csv(results: list[ModuleResult], output: Path):
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
    parser = argparse.ArgumentParser(description="Unified dependency comparison result collector.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Root of reproducible-central checkout")
    parser.add_argument("--mode", type=str, default="rq2", choices=["rq2", "base", "base_range"], help="Collection mode: rq2 or base")
    parser.add_argument("--range", type=str, default="major", choices=["pinned", "patch", "minor", "major"], help="Version range mode")
    parser.add_argument("--log-dir", type=Path, default=None, help="Directory with rebuild logs")
    parser.add_argument("--output", type=Path, default=None, help="Output CSV file path")
    parser.add_argument("--buildspecs", type=Path, nargs="*", help="Run rebuild.sh for these buildspecs before collecting")
    parser.add_argument("--rebuild-sh", type=Path, default=None, help="Path to rebuild.sh")
    parser.add_argument("--dry-run", action="store_true", help="Print rebuild commands without running them")
    parser.add_argument("--summary-only", action="store_true", help="Print summary table but don't write CSV")

    parser.add_argument("--lag", action="store_true", help="Also measure technical lag and version jumps")
    parser.add_argument("--lag-cache", type=Path, default=Path("results/.lag_cache.json"), help="Frozen Maven Central snapshot")
    parser.add_argument("--lag-refresh", action="store_true", help="Refetch release lists even if cached")
    parser.add_argument("--lag-scopes", type=str, default=None, help="Comma separated scopes to include")
    parser.add_argument("--lag-workers", type=int, default=4, help="Parallel requests to Maven Central")

    args = parser.parse_args()

    default_log_dir = "rq2_logs" if args.mode == "rq2" else "base_logs"
    log_dir = args.log_dir or (args.root / default_log_dir)

    if args.mode == "base":
        default_log_dir = "base_range_logs" if (args.root / "base_range_logs").exists() else "base_logs"
        default_output_prefix = "base_range_results"
    else:
        default_log_dir = "rq2_logs"
        default_output_prefix = "rq2_results"

    log_dir = args.log_dir or (args.root / default_log_dir)
    default_output = Path(f"results/{default_output_prefix}_{args.range}.csv")
    out = args.output or default_output

    if args.buildspecs:
        if not args.rebuild_sh or not args.rebuild_sh.exists():
            print("ERROR: --rebuild-sh must point to a valid rebuild.sh when using --buildspecs", file=sys.stderr)
            sys.exit(1)
        for spec in args.buildspecs:
            run_buildspec(args.rebuild_sh, spec, log_dir, dry_run=args.dry_run)

    results = collect_from_root(args.root, args.mode, args.range, log_dir)
    if not results:
        print("No results found. Have you run the builds yet?")
        sys.exit(0)

    default_output = Path(f"results/{args.mode}_results_{args.range}.csv")
    out = args.output or default_output

    if args.lag:
        # Snapshot original build status and build times before technical_lag enrichment
        build_status_backup = {(r.repo, r.module): (r.build_success, r.build_time_s) for r in results}
        
        detail_path = out.with_name(out.stem + "_lag_detail.csv")
        technical_lag.enrich(
            results, 
            args.range, 
            args.lag_cache, 
            refresh=args.lag_refresh,
            workers=args.lag_workers, 
            root=args.root,
            buildcache=None,
            scopes=set(args.lag_scopes.split(",")) if args.lag_scopes else None,
            detail_path=detail_path
        )
        
        # Restore the exact build success and timing metrics determined by log analysis
        for r in results:
            key = (r.repo, r.module)
            if key in build_status_backup:
                r.build_success, r.build_time_s = build_status_backup[key]
    print_summary(results, args.mode, args.range)

    if not args.summary_only:
        write_csv(results, out)


if __name__ == "__main__":
    main()