#!/usr/bin/env python3
"""
tables_rq2.py — LaTeX tables for RQ2.

Reads results/rq2_repo_flag_table.csv (written by graphs/graph_rq2.py), so the tables use exactly the
same numbers as the graphs. Run the graph script first.

Definitions (same as the graphs):
  * Failed builds are excluded from every statistic except the build success rate.
  * Test pass rate: mean over built repos of the per-repo rate (std is over the same repos).
  * Per-module means: mean over built repos of count / modules; repos that did not reach the
    comparison stage (no modules) are skipped.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FLAGS = ["major", "minor", "patch"]

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root (default: cwd)")
ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "tables")
a = ap.parse_args()

TABLE_CSV = a.root.resolve() / "results" / "rq2_repo_flag_table.csv"
TABLES_DIR = a.out
TABLES_DIR.mkdir(parents=True, exist_ok=True)

if not TABLE_CSV.exists():
    sys.exit(f"{TABLE_CSV} not found; run graphs/graph_rq2.py first")

# ------------------------------------------------------------------------------ load

tidy = pd.read_csv(TABLE_CSV)
if "rq1_built" not in tidy:
    print("[WARN] no rq1_built column; rerun the updated graph script. Treating RQ1 NaN as failed.",
          file=sys.stderr)
    tidy["rq1_built"] = tidy["rq1_pass_rate"].notna()

repos = sorted(tidy["repo"].unique())

# one row per (repo, flag); a repo with no row for a flag counts as not built
full = pd.MultiIndex.from_product([repos, FLAGS], names=["repo", "flag"])
tidy = tidy.set_index(["repo", "flag"]).reindex(full).reset_index()
tidy["built"] = tidy["built"].fillna(False).astype(bool)
for c in ("upgraded", "pinned", "downgraded", "modules"):
    if c not in tidy:
        tidy[c] = np.nan

# per-repo, per-module ratios; eligibility is the same as upgrades_per_module in the graph script
eligible = tidy["upgrades_per_module"].notna()
for c in ("upgraded", "pinned", "downgraded"):
    tidy[f"{c}_pm"] = np.where(eligible, tidy[c] / tidy["modules"], np.nan)

lookup = tidy.set_index(["repo", "flag"])
rq1_rate = tidy.groupby("repo")["rq1_pass_rate"].first()
rq1_ok = tidy.groupby("repo")["rq1_built"].first().fillna(False).astype(bool)


def cnt(v):
    return "--" if pd.isna(v) else f"{int(v)}"


def num(v, spec=".1f", suffix=""):
    return "--" if pd.isna(v) else f"{v:{spec}}{suffix}"


# ------------------------------------------------------------------------------ Table 1

CMARK, XMARK = r"\cmark", r"\xmark"

head = r"""\textbf{Repository} & \textbf{Flag} & \textbf{Upgraded} & \textbf{Pinned} & \textbf{Downgraded} & \textbf{Build} \\"""
latex_repo_table = "\n".join([
    r"\onecolumn",
    r"\begin{small}",
    r"\setlength{\tabcolsep}{4pt}",
    r"\begin{longtable}{llrrrr}",
    r"\caption{Per-Repository Dependency Actions and Build Status across Update Flags (failed builds excluded: --)} "
    r"\label{tab:repo_breakdown} \\",
    r"\toprule", head, r"\midrule", r"\endfirsthead",
    "",
    r"\multicolumn{6}{c}{{\tablename\ \thetable\ -- continued from previous page}} \\",
    r"\toprule", head, r"\midrule", r"\endhead",
    "",
    r"\midrule",
    r"\multicolumn{6}{r}{{Continued on next page}} \\",
    r"\endfoot",
    "",
    r"\bottomrule",
    r"\endlastfoot",
]) + "\n"

for n, repo in enumerate(repos):
    if n:
        latex_repo_table += "\\midrule\n"
    for i, flag in enumerate(FLAGS):
        r = lookup.loc[(repo, flag)]
        ok = bool(r["built"])
        name = repo if i == 0 else ""
        mark = CMARK if ok else XMARK
        latex_repo_table += (f"{name} & {flag.capitalize()} & {cnt(r['upgraded'])} & {cnt(r['pinned'])} & "
                             f"{cnt(r['downgraded'])} & {mark} \\\\\n")

latex_repo_table += "\\end{longtable}\n\\end{small}\n\\twocolumn"
(TABLES_DIR / "rq2_per_repo_breakdown.tex").write_text(latex_repo_table)
print("Saved: rq2_per_repo_breakdown.tex")

# ------------------------------------------------------------------------------ Table 2

fmt = {}
for f in FLAGS:
    t = tidy[tidy["flag"] == f]
    ok = t[t["built"]]
    fmt[f] = {
        "build": num(t["built"].mean() * 100, ".1f", "\\%"),
        "tests": num(ok["pass_rate"].mean(), ".1f", "\\%") + " $\\pm$ " + num(ok["pass_rate"].std(), ".1f"),
        "upg_total": f"{int(ok['upgraded'].sum()):,}",
        "upg": num(ok["upgraded_pm"].mean(), ".2f"),
        "pin": num(ok["pinned_pm"].mean(), ".2f"),
        "down": num(ok["downgraded_pm"].mean(), ".2f"),
    }


def cells(key):
    return " & ".join(fmt[f][key] for f in FLAGS)


latex_summary_table = "\n".join([
    r"\begin{table}[htbp]",
    r"\centering",
    r"\caption{Macro Summary Across Update Scopes (RQ2). Failed builds are excluded from every row except "
    r"the build success rate; per-module means are averaged over repositories.}",
    r"\label{tab:rq2_macro_summary}",
    r"\resizebox{\linewidth}{!}{%",
    r"\begin{tabular}{lccc}",
    r"\toprule",
    r"\textbf{Metric} & \textbf{Major} & \textbf{Minor} & \textbf{Patch} \\",
    r"\midrule",
    "Build Success Rate & " + cells("build") + r" \\",
    r"Test Pass Rate (Mean $\pm$ Std) & " + cells("tests") + r" \\",
    "Upgraded Dependencies (Total) & " + cells("upg_total") + r" \\",
    "Upgraded Dependencies (Mean per module) & " + cells("upg") + r" \\",
    "Pinned Dependencies (Mean per module) & " + cells("pin") + r" \\",
    "Downgraded Dependencies (Mean per module) & " + cells("down") + r" \\",
    r"\bottomrule",
    r"\end{tabular}%",
    r"}",
    r"\end{table}",
])
(TABLES_DIR / "rq2_per_flag_summary.tex").write_text(latex_summary_table)
print("Saved: rq2_per_flag_summary.tex")

# ------------------------------------------------------------------------------ Table 3


def pass_cell(v, built):
    if not built:
        return XMARK
    return "n/a" if pd.isna(v) else f"{v:.1f}\\%"


latex_test_table = "\n".join([
    r"\begin{table}[htbp]",
    r"\centering",
    r"\caption{Test Success Rate (\%) by Repository: RQ1 vs. RQ2 Update Flags (\xmark{} = build failed, excluded)}",
    r"\label{tab:test_success_rates}",
    r"\resizebox{\linewidth}{!}{%",
    r"\begin{tabular}{lrrrr}",
    r"\toprule",
    r"\textbf{Repository} & \textbf{RQ1 (\%)} & \textbf{Major (\%)} & \textbf{Minor (\%)} & \textbf{Patch (\%)} \\",
    r"\midrule",
]) + "\n"

for repo in repos:
    cols = [pass_cell(rq1_rate[repo], rq1_ok[repo])]
    for f in FLAGS:
        r = lookup.loc[(repo, f)]
        cols.append(pass_cell(r["pass_rate"], bool(r["built"])))
    latex_test_table += f"{repo} & " + " & ".join(cols) + " \\\\\n"

latex_test_table += "\\bottomrule\n\\end{tabular}%\n}\n\\end{table}"
(TABLES_DIR / "rq2_test_success_rates.tex").write_text(latex_test_table)
print("Saved: rq2_test_success_rates.tex")