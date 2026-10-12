#!/usr/bin/env python3
"""
collect_rq1_results.py — Collect RQ1-style build and equivalence results.

For RQ1 (pinned flattening, no version ranges), checks:
  1. Did the build compile and pass tests? (from the rebuild.sh log)
  2. Is the flattened dep tree semantically equivalent to the original?
     Since no ranges are used, UPGRADED/DOWNGRADED should be 0 and
     all deps in the before snapshot should appear in the after snapshot.
     ADDED entries are expected (promoted transitives) and not a failure.
     REMOVED entries indicate a flattening bug.

The same statistics are also collected for the RQ2 flavors (RQ2major, RQ2minor,
RQ2patch) via --flavor.

Build success
-------------
A repo's build succeeded only if the LAST Maven verdict in its log is BUILD SUCCESS.
The log is the most recent one whose name matches both the repo and the flavor
(<repo>_<anything containing the flavor>.log). A repo that has a log but produced no
comparison reports (e.g. the build failed before any module was flattened) is still
reported, as a failed build with 0 modules.

Usage:
    python collect_rq1_results.py --root ~/reproducible-central --output results/rq1_results.csv
    python collect_rq1_results.py --root ~/reproducible-central --flavor RQ2major \
        --log-dir ~/reproducible-central/rq2_logs --output results/rq1_style_stats_major.csv
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


ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ----------------------------------------------------------------------------- build success
# (also imported by collect_results.py)

def log_build_success(log_path: Path) -> bool:
    """True only if Maven's last verdict in the log is BUILD SUCCESS.

    No verdict at all (docker failure, timeout, aborted run) counts as a failure.
    """
    try:
        text = ANSI.sub("", log_path.read_text(errors="replace"))
    except OSError:
        return False
    ok = text.rfind("BUILD SUCCESS")
    bad = text.rfind("BUILD FAILURE")
    return ok != -1 and ok > bad


def find_flavor_log(log_dir: Optional[Path], repo: str, flavor: str) -> Optional[Path]:
    """Most recent log for this repo AND this flavor, or None.

    Log names look like <repo>_<spec>.log, where the spec name contains the flavor
    (e.g. juneau_juneauRQ2major.log). Matching on both keeps the major/minor/patch
    runs of one repo from being mixed up, and the repo is matched exactly as a prefix,
    so 'api' never picks up the logs of 'api-client'.
    """
    if log_dir is None or not log_dir.is_dir():
        return None
    prefix = repo.lower() + "_"
    flavor_l = flavor.lower()
    matches = []
    for p in log_dir.glob("*.log"):
        stem = p.stem.lower()
        if stem.startswith(prefix) and flavor_l in stem[len(prefix):]:
            matches.append(p)
    return max(matches, key=lambda p: p.stat().st_mtime, default=None)


# ----------------------------------------------------------------------------- parsing

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

        # Semantic equivalence: no version changes, no removals and nothing added.
        result.equivalent = (
            result.upgraded == 0
            and result.downgraded == 0
            and result.removed == 0
            and result.added == 0
            and not result.skipped_flatten
        )
        return result
    except Exception as e:
        print(f"[WARN] Failed to parse {report_path}: {e}", file=sys.stderr)
        return None


def parse_surefire_reports(build_root: Path) -> tuple[int, int, int, int]:
    """
    Parse all Surefire/Failsafe XML reports anywhere under build_root.
    Returns (tests_run, failures, errors, skipped).
    """
    import xml.etree.ElementTree as ET

    total = failures = errors = skipped = 0
    processed_files = set()

    for report_dir_name in ("surefire-reports", "failsafe-reports"):
        for report_dir in build_root.rglob(report_dir_name):
            if not report_dir.is_dir():
                continue

            for xml_file in report_dir.glob("TEST-*.xml"):
                xml_file = xml_file.resolve()

                if xml_file in processed_files:
                    continue
                processed_files.add(xml_file)

                try:
                    root = ET.parse(xml_file).getroot()

                    if root.tag == "testsuite":
                        suites = [root]
                    else:
                        suites = root.findall("testsuite")

                    for suite in suites:
                        total += int(suite.get("tests", 0))
                        failures += int(suite.get("failures", 0))
                        errors += int(suite.get("errors", 0))
                        skipped += int(suite.get("skipped", 0))

                except Exception as e:
                    print(
                        f"[WARN] Could not parse {xml_file}: {e}",
                        file=sys.stderr
                    )

    return total, failures, errors, skipped


# ----------------------------------------------------------------------------- collection

def collect_repo(buildcache: Path, repo: str, log: Path):
    """Collect all module results for one repo.

    Returns (module results, buildcache-wide test totals, build_success).
    """
    results = []

    # Find all comparison reports; each lives in <module>/target/
    for report_path in sorted(
        buildcache.rglob("dependency-comparison-report.txt")
    ):
        result = parse_comparison_report(report_path, repo)

        if not result:
            continue

        # Tests of this module only (its own target/ directory)
        run, fail, err, skip = parse_surefire_reports(report_path.parent)
        result.tests_run = run
        result.tests_failed = fail
        result.tests_errored = err
        result.tests_skipped = skip

        results.append(result)

    # Find test reports across the ENTIRE buildcache.
    test_totals = parse_surefire_reports(buildcache)

    build_success = log_build_success(log)
    for r in results:
        r.build_success = build_success

    return results, test_totals, build_success


def summarise_repo(
    repo,
    results,
    build_success,
    test_totals=(0, 0, 0, 0),
):
    module_run  = sum(r.tests_run for r in results)
    module_fail = sum(r.tests_failed for r in results)
    module_err  = sum(r.tests_errored for r in results)
    module_skip = sum(r.tests_skipped for r in results)

    # Prefer the complete buildcache-wide test discovery; fall back to the
    # per-module values if it found nothing.
    run, fail, err, skip = test_totals

    if run == 0:
        run, fail, err, skip = (
            module_run,
            module_fail,
            module_err,
            module_skip,
        )

    passed = run - fail - err - skip

    modules_with_tests = sum(
        1 for r in results if r.tests_run > 0
    )

    equiv = sum(
        1 for r in results
        if r.equivalent and not r.skipped_flatten
    )

    nonequiv = sum(
        1 for r in results
        if not r.equivalent and not r.skipped_flatten
    )

    return RepoSummary(
        repo=repo,
        build_success=build_success,
        total_modules=len(results),
        modules_with_tests=modules_with_tests,
        total_tests=run,
        total_passed=passed,
        total_failed=fail,
        total_errored=err,
        total_skipped=skip,
        equivalent_modules=equiv,
        non_equivalent_modules=nonequiv,
        skipped_flatten=sum(
            1 for r in results if r.skipped_flatten
        ),
        upgraded_count=sum(r.upgraded for r in results),
        downgraded_count=sum(r.downgraded for r in results),
        removed_count=sum(r.removed for r in results),
        added_count=sum(r.added for r in results),
    )


def print_summary(summaries: list[RepoSummary], flavor: str = "RQ1"):
    print(f"\n{'='*80}")
    print(f"  RQ1-style Results — {flavor}")
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

    non_equiv_detail = [s for s in summaries if s.non_equivalent_modules > 0]

    if non_equiv_detail:
        print("  Non-equivalent modules (potential flattening bugs):")
        for s in non_equiv_detail:
            print(f"    {s.repo}: upgraded={s.upgraded_count} downgraded={s.downgraded_count} removed={s.removed_count}")
        print()


def write_csvs(summaries: list[RepoSummary], all_results: list[ModuleResult], output: Path):
    """Write repo-level summary CSV and module-level detail CSV."""
    output.parent.mkdir(parents=True, exist_ok=True)

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
        description="Collect RQ1-style build and equivalence results from reproducible-central builds."
    )
    parser.add_argument("--root", type=Path, required=True,
                        help="Root of reproducible-central checkout")
    parser.add_argument("--output", type=Path, default=Path("results/rq1_results.csv"),
                        help="Output CSV file path (default: results/rq1_results.csv); "
                             "the module-level CSV is written next to it with a _modules suffix")
    parser.add_argument("--log-dir", type=Path, default=None,
                        help="Directory containing rebuild.sh log files (default: <root>/rq1_logs)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary table but don't write CSV")
    parser.add_argument("--flavor", default="RQ1",
                        help="Flavor directory to collect, e.g. RQ1, RQ2major, RQ2minor, RQ2patch")
    args = parser.parse_args()

    log_dir = args.log_dir or (args.root / "rq1_logs")
    if not log_dir.is_dir():
        print(f"[WARN] Log directory {log_dir} does not exist — nothing can be matched to a build result.",
              file=sys.stderr)

    all_results: list[ModuleResult] = []
    summaries: list[RepoSummary] = []

    for buildcache in sorted(args.root.rglob("buildcache")):
        if not buildcache.is_dir():
            continue

        try:
            relative = buildcache.relative_to(args.root / "repos")
        except ValueError:
            continue
        if len(relative.parts) != 3:  # <repo>/<flavor>/buildcache
            print(f"[SKIP] Unexpected buildcache depth: {buildcache}", file=sys.stderr)
            continue

        repo, flavor, _ = relative.parts
        if flavor != args.flavor:
            continue

        # Only report repos the pipeline actually ran for THIS flavor: a repo without a
        # matching log is a stale buildcache from an earlier experiment.
        log = find_flavor_log(log_dir, repo, args.flavor)
        if log is None:
            print(f"[SKIP] {repo}: no {args.flavor} log in {log_dir} (stale buildcache?)", file=sys.stderr)
            continue

        results, test_totals, build_success = collect_repo(buildcache, repo, log)
        if not results:
            # Typically the build failed before any module was flattened.
            # Still record the repo, with its true build status and 0 modules.
            print(f"[WARN] {repo}: no comparison reports in {buildcache} — recorded as "
                  f"build={'PASS' if build_success else 'FAIL'} with 0 modules (log: {log.name})",
                  file=sys.stderr)

        summaries.append(summarise_repo(repo, results, build_success, test_totals=test_totals))
        all_results.extend(results)
        print(f"[OK]   {repo}: {len(results)} modules, build={'PASS' if build_success else 'FAIL'}",
              file=sys.stderr)

    if not summaries:
        print(f"No results found for flavor {args.flavor}. Have you run the builds yet?")
        sys.exit(0)

    print_summary(summaries, args.flavor)

    if not args.summary_only:
        write_csvs(summaries, all_results, args.output)


if __name__ == "__main__":
    main()