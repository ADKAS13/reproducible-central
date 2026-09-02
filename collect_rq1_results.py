#!/usr/bin/env python3
"""
collect_rq1_results.py — Collect RQ1 build and equivalence results.

For RQ1 (pinned flattening, no version ranges), checks:
  1. Did the build compile and pass tests? (from rebuild.sh log)
  2. Is the flattened dep tree semantically equivalent to the original?
     Since no ranges are used, UPGRADED/DOWNGRADED should be 0 and
     all deps in the before snapshot should appear in the after snapshot.
     ADDED entries are expected (promoted transitives) and not a failure.
     REMOVED entries indicate a flattening bug.

Usage:
    python collect_rq1_results.py --root ~/reproducible-central --output rq1_results.csv
    python collect_rq1_results.py --root ~/reproducible-central --log-dir ~/reproducible-central/rq1_logs
"""

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ModuleResult:
    repo: str
    module: str
    build_success: bool = False
    tests_run: int = 0
    tests_failed: int = 0
    tests_errored: int = 0
    tests_skipped: int = 0
    pinned: int = 0
    upgraded: int = 0
    downgraded: int = 0
    added: int = 0
    removed: int = 0
    scope_changed: int = 0
    skipped_flatten: bool = False
    equivalent: bool = False  # True if upgraded==0, downgraded==0, removed==0

    @property
    def tests_passed(self):
        return self.tests_run - self.tests_failed - self.tests_errored - self.tests_skipped

    @property
    def pass_rate(self):
        if self.tests_run == 0:
            return None
        return round(self.tests_passed / self.tests_run * 100, 1)


@dataclass
class RepoSummary:
    repo: str
    build_success: bool
    total_modules: int
    modules_with_tests: int
    total_tests: int
    total_passed: int
    total_failed: int
    total_errored: int
    total_skipped: int
    equivalent_modules: int
    non_equivalent_modules: int
    skipped_flatten: int
    upgraded_count: int
    downgraded_count: int
    removed_count: int
    added_count: int

    @property
    def pass_rate(self):
        if self.total_tests == 0:
            return None
        return round(self.total_passed / self.total_tests * 100, 1)

    @property
    def equivalence_rate(self):
        checked = self.equivalent_modules + self.non_equivalent_modules
        if checked == 0:
            return None
        return round(self.equivalent_modules / checked * 100, 1)


def parse_comparison_report(report_path: Path, repo: str) -> Optional[ModuleResult]:
    """Parse a dependency-comparison-report.txt into a ModuleResult."""
    result = ModuleResult(repo=repo, module="")
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
                elif line.startswith("SKIPPED=true"):
                    result.skipped_flatten = True

        # Semantic equivalence: no version changes and no removals.
        # ADDED is allowed (promoted transitives are structural, not semantic changes).
        # SCOPE_CHANGED is allowed (flattening changes effective scope by depth).
        result.equivalent = (
            result.upgraded == 0
            and result.downgraded == 0
            and result.removed == 0
            and not result.skipped_flatten
        )
        return result
    except Exception as e:
        print(f"[WARN] Failed to parse {report_path}: {e}", file=sys.stderr)
        return None


def parse_surefire_reports(module_target: Path) -> tuple[int, int, int, int]:
    """
    Parse surefire XML reports in target/surefire-reports/ for a module.
    Returns (tests_run, failures, errors, skipped).
    """
    surefire_dir = module_target / "surefire-reports"
    if not surefire_dir.exists():
        return 0, 0, 0, 0

    import xml.etree.ElementTree as ET
    total, failures, errors, skipped = 0, 0, 0, 0
    for xml_file in surefire_dir.glob("TEST-*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            total    += int(root.get("tests",    0))
            failures += int(root.get("failures", 0))
            errors   += int(root.get("errors",   0))
            skipped  += int(root.get("skipped",  0))
        except Exception:
            pass
    return total, failures, errors, skipped


def parse_build_log(log_path: Path) -> bool:
    """Check if the build log indicates overall success."""
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(errors="replace")
        # Look for the reactor summary success marker
        return "BUILD SUCCESS" in content
    except Exception:
        return False


def collect_repo(buildcache: Path, repo: str, log_dir: Path) -> list[ModuleResult]:
    """Collect all module results for one repo."""
    results = []

    # Find all comparison reports
    for report_path in sorted(buildcache.rglob("dependency-comparison-report.txt")):
        result = parse_comparison_report(report_path, repo)
        if not result:
            continue

        # Find surefire reports relative to the comparison report
        module_target = report_path.parent
        runs, fails, errs, skipped = parse_surefire_reports(module_target)
        result.tests_run     = runs
        result.tests_failed  = fails
        result.tests_errored = errs
        result.tests_skipped = skipped

        results.append(result)

    # Determine overall build success from log
    # Look for log file matching this repo
    build_success = False
    for log_file in sorted(log_dir.glob(f"{repo}_*.log")):
        if parse_build_log(log_file):
            build_success = True
            break

    for r in results:
        r.build_success = build_success

    return results


def summarise_repo(repo: str, results: list[ModuleResult], build_success: bool) -> RepoSummary:
    """Aggregate module results into a repo-level summary."""
    modules_with_tests = sum(1 for r in results if r.tests_run > 0)
    equiv   = sum(1 for r in results if r.equivalent and not r.skipped_flatten)
    nonequiv= sum(1 for r in results if not r.equivalent and not r.skipped_flatten)

    return RepoSummary(
        repo=repo,
        build_success=build_success,
        total_modules=len(results),
        modules_with_tests=modules_with_tests,
        total_tests=sum(r.tests_run for r in results),
        total_passed=sum(r.tests_passed for r in results),
        total_failed=sum(r.tests_failed for r in results),
        total_errored=sum(r.tests_errored for r in results),
        total_skipped=sum(r.tests_skipped for r in results),
        equivalent_modules=equiv,
        non_equivalent_modules=nonequiv,
        skipped_flatten=sum(1 for r in results if r.skipped_flatten),
        upgraded_count=sum(r.upgraded for r in results),
        downgraded_count=sum(r.downgraded for r in results),
        removed_count=sum(r.removed for r in results),
        added_count=sum(r.added for r in results),
    )


def print_summary(summaries: list[RepoSummary]):
    print(f"\n{'='*80}")
    print(f"  RQ1 Results — Pinned Flattening")
    print(f"{'='*80}")
    print(f"{'Repo':<30} {'Build':>6} {'Tests':>7} {'Pass%':>6} {'Equiv':>6} {'Equiv%':>7} {'Added':>6} {'Removed':>8}")
    print(f"{'-'*80}")

    for s in sorted(summaries, key=lambda x: x.repo):
        build  = "PASS" if s.build_success else "FAIL"
        prate  = f"{s.pass_rate:.1f}%" if s.pass_rate is not None else "  N/A"
        erate  = f"{s.equivalence_rate:.1f}%" if s.equivalence_rate is not None else "  N/A"
        equiv  = f"{s.equivalent_modules}/{s.equivalent_modules + s.non_equivalent_modules}"
        print(f"{s.repo:<30} {build:>6} {s.total_tests:>7} {prate:>6} {equiv:>6} {erate:>7} {s.added_count:>6} {s.removed_count:>8}")

    print(f"{'='*80}")

    # Totals
    total_build_pass = sum(1 for s in summaries if s.build_success)
    total_tests  = sum(s.total_tests for s in summaries)
    total_passed = sum(s.total_passed for s in summaries)
    total_equiv  = sum(s.equivalent_modules for s in summaries)
    total_nonequiv = sum(s.non_equivalent_modules for s in summaries)
    total_pass_rate = f"{total_passed/total_tests*100:.1f}%" if total_tests else "N/A"
    total_equiv_rate = f"{total_equiv/(total_equiv+total_nonequiv)*100:.1f}%" if (total_equiv+total_nonequiv) else "N/A"

    print(f"\n  Build:       {total_build_pass}/{len(summaries)} repos passed")
    print(f"  Tests:       {total_passed}/{total_tests} passed ({total_pass_rate})")
    print(f"  Equivalence: {total_equiv}/{total_equiv+total_nonequiv} modules equivalent ({total_equiv_rate})")
    print(f"{'='*80}\n")

    # Flag any non-equivalent modules
    all_results = []
    for s in summaries:
        all_results.extend([s.repo])

    non_equiv_detail = []
    for s in summaries:
        if s.non_equivalent_modules > 0:
            non_equiv_detail.append(s)

    if non_equiv_detail:
        print("  Non-equivalent modules (potential flattening bugs):")
        for s in non_equiv_detail:
            print(f"    {s.repo}: upgraded={s.upgraded_count} downgraded={s.downgraded_count} removed={s.removed_count}")
        print()


def write_csvs(summaries: list[RepoSummary], all_results: list[ModuleResult], output: Path):
    """Write repo-level summary CSV and module-level detail CSV."""
    # Repo summary CSV
    repo_csv = output
    repo_fields = [f.name for f in fields(RepoSummary)]
    with open(repo_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=repo_fields + ["pass_rate", "equivalence_rate"])
        writer.writeheader()
        for s in summaries:
            row = asdict(s)
            row["pass_rate"] = s.pass_rate
            row["equivalence_rate"] = s.equivalence_rate
            writer.writerow(row)
    print(f"Repo summary written to {repo_csv} ({len(summaries)} repos)")

    # Module detail CSV
    module_csv = output.with_name(output.stem + "_modules" + output.suffix)
    mod_fields = [f.name for f in fields(ModuleResult)] + ["tests_passed", "pass_rate"]
    with open(module_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=mod_fields)
        writer.writeheader()
        for r in all_results:
            row = asdict(r)
            row["tests_passed"] = r.tests_passed
            row["pass_rate"] = r.pass_rate
            writer.writerow(row)
    print(f"Module detail written to {module_csv} ({len(all_results)} modules)")


def main():
    parser = argparse.ArgumentParser(
        description="Collect RQ1 build and equivalence results from reproducible-central builds."
    )
    parser.add_argument("--root", type=Path, required=True,
                        help="Root of reproducible-central checkout")
    parser.add_argument("--output", type=Path, default=Path("rq1_results.csv"),
                        help="Output CSV file path (default: rq1_results.csv)")
    parser.add_argument("--log-dir", type=Path, default=None,
                        help="Directory containing rebuild.sh log files (default: <root>/rq1_logs)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary table but don't write CSV")
    args = parser.parse_args()

    log_dir = args.log_dir or (args.root / "rq1_logs")

    # Discover repos via buildcache directories
    all_results: list[ModuleResult] = []
    summaries: list[RepoSummary] = []

    for buildcache in sorted(args.root.rglob("buildcache")):
        if not buildcache.is_dir():
            continue
        repo = buildcache.parent.name

        results = collect_repo(buildcache, repo, log_dir)
        if not results:
            continue

        build_success = any(r.build_success for r in results)
        summary = summarise_repo(repo, results, build_success)
        summaries.append(summary)
        all_results.extend(results)

    if not summaries:
        print("No results found. Have you run the RQ1 builds yet?")
        sys.exit(0)

    print_summary(summaries)

    if not args.summary_only:
        write_csvs(summaries, all_results, args.output)


if __name__ == "__main__":
    main()