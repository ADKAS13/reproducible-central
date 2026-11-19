#!/usr/bin/env python3
"""
check_build_rates.py — ground truth for build rates, straight from the logs, next to what each CSV says.

Run from the reproducible-central root:
    python3 check_build_rates.py [--root .] [--rq2-stages 1] [--base-stages 3]

For every flag (major/minor/patch) and both variants (rq2, base) it prints:
  logs      repos whose last Maven verdict is BUILD SUCCESS (and that reported enough stages)
  dep CSV   repos with build_success=True in rq2_results_<flag>.csv / base_results_<flag>.csv
  stats CSV repos with build_success=True in rq1_style_stats_<flag>.csv / base_rq1_style_stats_<flag>.csv
then lists the repos where a CSV disagrees with the logs, and whether rq2 and base really have the
same set of passing repos. Whichever source the graphs read from, this shows if it matches reality.
"""
import argparse
import re
from pathlib import Path

import pandas as pd

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FLAGS = ["major", "minor", "patch"]


def log_result(path, stages):
    text = ANSI.sub("", path.read_text(errors="replace"))
    ok, bad = text.count("BUILD SUCCESS"), text.count("BUILD FAILURE")
    last_ok = text.rfind("BUILD SUCCESS") > text.rfind("BUILD FAILURE")
    return last_ok and ok >= stages and bad == 0


def repo_of(stem, marker):
    i = stem.lower().rfind(marker.lower())
    if i <= 1:
        return None
    spec = stem[:i]                       # "<repo>_<repo>"
    return spec[: (len(spec) - 1) // 2]


def from_logs(root, kind, flag, stages):
    d = root / (f"rq2_logs_{flag}" if kind == "rq2" else f"base_logs_{flag}")
    marker = f"RQ2{flag}" if kind == "rq2" else f"Base{flag.capitalize()}"
    flavor_dir = marker if kind == "rq2" else f"base{flag.capitalize()}"
    out, stale = {}, []
    if d.is_dir():
        for p in sorted(d.glob("*.log"), key=lambda q: q.stat().st_mtime):
            r = repo_of(p.stem, marker)
            if not r:
                continue
            if not (root / "repos" / r / flavor_dir).is_dir():
                stale.append(r)                      # log of a repo/flavor that is no longer in the dataset
                continue
            out[r] = log_result(p, stages)           # newest log wins
    return out, sorted(set(stale))


def first_existing(res, names):
    for n in names:
        if (res / n).exists():
            return res / n
    return None


def from_csv(path):
    if not path.exists():
        return None
    d = pd.read_csv(path)
    if "build_success" not in d:
        return None
    return {r: bool(g.astype(str).str.lower().eq("true").iloc[0]) for r, g in d.groupby("repo")["build_success"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--rq2-stages", type=int, default=1, help="BUILD SUCCESS lines a passing RQ2 log must have")
    ap.add_argument("--base-stages", type=int, default=3)
    a = ap.parse_args()
    res = a.root / "results"

    built_sets = {}
    print(f"{'flag':6} {'variant':8} {'logs':>10} {'dep CSV':>10} {'stats CSV':>10}")
    for f in FLAGS:
        for kind, stages, dep_name, stats_name in (
                ("rq2", a.rq2_stages, f"rq2_results_{f}.csv", f"rq1_style_stats_{f}.csv"),
                ("base", a.base_stages, f"base_results_{f}.csv", f"base_rq1_style_stats_{f}.csv")):
            logs, stale = from_logs(a.root, kind, f, stages)
            dep_path = first_existing(res, [dep_name, f"{kind}_results_{f}.csv", f"{kind}_range_results_{f}.csv", f"{kind}_ranges_results_{f}.csv"])
            stats_path = first_existing(res, [stats_name, f"{kind}_{stats_name}", f"{kind}_rq1_style_stats_{f}.csv"])
            dep = from_csv(dep_path) if dep_path else None
            stats = from_csv(stats_path) if stats_path else None
            built_sets[(kind, f)] = {r for r, ok in logs.items() if ok}

            def cell(d):
                return "missing" if d is None else f"{sum(d.values())}/{len(d)}"
            print(f"{f:6} {kind:8} {cell(logs):>10} {cell(dep):>10} {cell(stats):>10}"
                  f"   dep={dep_path.name if dep_path else '-'} stats={stats_path.name if stats_path else '-'}")
            if stale:
                print(f"         ignored {len(stale)} log(s) with no repos/<repo>/<flavor> folder: " + ", ".join(stale[:6])
                      + (" ..." if len(stale) > 6 else ""))

            for name, d in (("dep CSV", dep), ("stats CSV", stats)):
                if d is None:
                    continue
                diff = sorted(r for r in set(d) | set(logs) if d.get(r) != logs.get(r))
                if diff:
                    print(f"         {name} disagrees with the logs for {len(diff)} repo(s): "
                          + ", ".join(f"{r}(csv={d.get(r)}, log={logs.get(r)})" for r in diff[:8])
                          + (" ..." if len(diff) > 8 else ""))
    print()
    for f in FLAGS:
        same = built_sets[("rq2", f)] == built_sets[("base", f)]
        print(f"{f}: rq2 and base have {'the SAME' if same else 'different'} set of passing repos"
              f" ({len(built_sets[('rq2', f)])} vs {len(built_sets[('base', f)])})")


if __name__ == "__main__":
    main()