#!/usr/bin/env python3
"""
collect_base_results.py — Collect base build success and test pass rates.

For base builds, checks:
  1. Did the build succeed? (from rebuild.sh log files)
  2. Test execution and pass rates (from Surefire/Failsafe XML reports)

Usage:
    python collect_base_results.py --root ~/reproducible-central --output results/base_results.csv
    python collect_base_results.py --root ~/reproducible-central --log-dir ~/reproducible-central/base_logs
"""

import argparse
import csv
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class ModuleResult:
    repo: str
    module: str
    build_success: bool = False
    tests_run: int = 0
    tests_failed: int = 0
    tests_errored: int = 0
    tests_skipped: int = 0

    @property
    def tests_passed(self) -> int:
        return self.tests_run - self.tests_failed - self.tests_errored - self.tests_skipped

    @property
    def pass_rate(self) -> float | None:
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

    @property
    def pass_rate(self) -> float | None:
        if self.total_tests == 0:
            return None
        return round(self.total_passed / self.total_tests * 100, 1)


def parse_surefire_reports(module_target: Path) -> tuple[int, int, int, int]:
    """
    Parse surefire AND failsafe XML reports for a module target folder.
    Returns (tests_run, failures, errors, skipped).
    """
    total, failures, errors, skipped = 0, 0, 0, 0

    for report_dir_name in ("surefire-reports", "failsafe-reports"):
        report_dir = module_target / report_dir_name
        if not report_dir.exists():
            continue
        for xml_file in report_dir.glob("TEST-*.xml"):
            try:
                root = ET.parse(xml_file).getroot()
                total += int(root.get("tests", 0))
                failures += int(root.get("failures", 0))
                errors += int(root.get("errors", 0))
                skipped += int(root.get("skipped", 0))
            except Exception:
                pass

    return total, failures, errors, skipped


def parse_build_log(log_path: Path) -> bool:
    """Check if the build log indicates overall success."""
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(errors="replace")
        return "BUILD SUCCESS" in content
    except Exception:
        return False


def collect_repo(repo_dir: Path, repo: str, log_dir: Path) -> list[ModuleResult]:
    """Collect test results across all module target directories for one repo."""
    results = []

    # Find all target directories containing test reports
    target_dirs = set()
    for report_dir_name in ("surefire-reports", "failsafe-reports"):
        for report_dir in repo_dir.rglob(report_dir_name):
            if report_dir.is_dir():
                target_dirs.add(report_dir.parent)

    for target_dir in sorted(target_dirs):
        # Infer module relative path
        try:
            rel_path = target_dir.parent.relative_to(repo_dir)
            module_name = str(rel_path) if str(rel_path) != "." else repo
        except ValueError:
            module_name = target_dir.parent.name

        runs, fails, errs, skipped = parse_surefire_reports(target_dir)
        if runs == 0 and fails == 0 and errs == 0 and skipped == 0:
            continue

        result = ModuleResult(
            repo=repo,
            module=module_name,
            tests_run=runs,
            tests_failed=fails,
            tests_errored=errs,
            tests_skipped=skipped,
        )
        results.append(result)

    # Determine overall build success from build log
    build_success = False
    for log_file in sorted(log_dir.glob("*.log")):
        if log_file.stem.lower().startswith(repo.lower()):
            if parse_build_log(log_file):
                build_success = True
                break

    # Fallback log check
    if not build_success:
        for log_file in sorted(log_dir.glob("*.log")):
            try:
                content = log_file.read_text(errors="replace")
                if repo.lower() in content.lower() and "BUILD SUCCESS" in content:
                    build_success = True
                    break
            except Exception:
                continue

    for r in results:
        r.build_success = build_success

    # If no test modules were found, record a top-level module entry to track build status
    if not results:
        results.append(ModuleResult(repo=repo, module=repo, build_success=build_success))

    return results


def summarise_repo(repo: str, results: list[ModuleResult], build_success: bool) -> RepoSummary:
    """Aggregate module results into a repo-level summary."""
    modules_with_tests = sum(1 for r in results if r.tests_run > 0)

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
    )


def print_summary(summaries: list[RepoSummary]):
    print(f"\n{'='*60}")
    print("  Base Results — Build & Test Execution")
    print(f"{'='*60}")
    print(f"{'Repo':<30} {'Build':>8} {'Tests':>8} {'Passed':>8} {'Pass%':>8}")
    print(f"{'-'*60}")

    for s in sorted(summaries, key=lambda x: x.repo):
        build = "PASS" if s.build_success else "FAIL"
        prate = f"{s.pass_rate:.1f}%" if s.pass_rate is not None else "N/A"
        print(f"{s.repo:<30} {build:>8} {s.total_tests:>8} {s.total_passed:>8} {prate:>8}")

    print(f"{'='*60}")

    total_build_pass = sum(1 for s in summaries if s.build_success)
    total_tests = sum(s.total_tests for s in summaries)
    total_passed = sum(s.total_passed for s in summaries)
    total_pass_rate = f"{total_passed / total_tests * 100:.1f}%" if total_tests else "N/A"

    print(f"\n  Build Success Rate: {total_build_pass}/{len(summaries)} repos ({total_build_pass / len(summaries) * 100:.1f}%)")
    print(f"  Test Pass Rate:    {total_passed}/{total_tests} passed ({total_pass_rate})")
    print(f"{'='*60}\n")


def write_csvs(summaries: list[RepoSummary], all_results: list[ModuleResult], output: Path):
    """Write repo-level summary CSV and module-level detail CSV."""
    output.parent.mkdir(parents=True, exist_ok=True)

    # Repo summary CSV
    repo_fields = [f.name for f in fields(RepoSummary)] + ["pass_rate"]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=repo_fields)
        writer.writeheader()
        for s in summaries:
            row = asdict(s)
            row["pass_rate"] = s.pass_rate
            writer.writerow(row)
    print(f"Repo summary written to {output} ({len(summaries)} repos)")

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
        description="Collect Base build success and test pass rates."
    )
    parser.add_argument("--root", type=Path, required=True,
                        help="Root of reproducible-central checkout")
    parser.add_argument("--output", type=Path, default=Path("results/base_results.csv"),
                        help="Output CSV file path (default: results/base_results.csv)")
    parser.add_argument("--log-dir", type=Path, default=None,
                        help="Directory containing build log files (default: <root>/base_logs)")
    parser.add_argument("--summary-only", action="store_true",
                        help="Print summary table but don't write CSV")
    args = parser.parse_args()

    log_dir = args.log_dir or (args.root / "base_logs")

    all_results: list[ModuleResult] = []
    summaries: list[RepoSummary] = []

    logged_repos = set()
    if log_dir.exists():
        for log_file in sorted(log_dir.glob("*.log")):
            repo_name = log_file.stem.split("_")[0]
            logged_repos.add(repo_name.lower())

    if not logged_repos:
        print(f"[WARN] No log files found in {log_dir}", file=sys.stderr)

    repos_dir = args.root / "repos"
    if not repos_dir.exists():
        print(f"[ERROR] Repos directory does not exist at {repos_dir}", file=sys.stderr)
        sys.exit(1)

    for repo_path in sorted(repos_dir.iterdir()):
        if not repo_path.is_dir():
            continue

        base_dir = repo_path / "base"
        target_dir = base_dir if base_dir.exists() else repo_path

        repo_name = repo_path.name
        if logged_repos and repo_name.lower() not in logged_repos:
            continue

        results = collect_repo(target_dir, repo_name, log_dir)
        build_success = any(r.build_success for r in results) if results else parse_build_log(log_dir / f"{repo_name}.log")

        summary = summarise_repo(repo_name, results, build_success)
        summaries.append(summary)
        all_results.extend(results)
        print(f"[OK]   {repo_name}: {summary.total_tests} tests, build={'PASS' if build_success else 'FAIL'}", file=sys.stderr)

    if not summaries:
        print("No results found.")
        sys.exit(0)

    print_summary(summaries)

    if not args.summary_only:
        write_csvs(summaries, all_results, args.output)


if __name__ == "__main__":
    main()