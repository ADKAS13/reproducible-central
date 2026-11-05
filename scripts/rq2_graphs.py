#!/usr/bin/env python3
"""
graph_rq2.py — graphs for RQ2 (version ranges: major / minor / patch).

Run from the reproducible-central root (or pass --root):
    python3 graphs/graph_rq2.py
    python3 graphs/graph_rq2.py --root ~/reproducible-central --exclude zeebe-hazelcast-exporter

Inputs (all re-read on every run; nothing is cached):
    results/rq2_results_{flag}.csv                dependency changes per module   (collect_rq2_results.py)
    results/rq1_style_stats_{flag}.csv            tests per repo                   (collect_rq1_results.py)
    results/rq1_style_stats_{flag}_modules.csv    tests + upgrades per module
    results/rq1_results.csv                       RQ1 (pinned) baseline per repo
    rq2_logs_{flag}/*.log                         pipeline logs -> build outcome per repo

Build success comes from the logs, not from rq2_results_*.csv: that CSV only has rows for
modules that produced a comparison report, and its build_success column is always True.
"""

import argparse
import sys
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid")

FLAGS = ["major", "minor", "patch"]
COLORS = {"major": "#4c72b0", "minor": "#dd8452", "patch": "#55a868", "RQ1": "#8172b3"}
ACTIONS = ["pinned", "upgraded", "downgraded", "added", "removed", "scope_changed"]

# The collector counts skipped tests as "not passed". Set True to drop them from the denominator.
PASS_RATE_EXCLUDES_SKIPPED = False

# ------------------------------------------------------------------------------ loading

def read(path):
    return pd.read_csv(path) if path.exists() else None


def outcome_of(path):
    text = ANSI.sub("", path.read_text(errors="replace"))
    if "BUILD SUCCESS" in text and "BUILD FAILURE" not in text:
        return "success"
    if "BUILD FAILURE" not in text:
        return "incomplete"
    m = FAILED_GOAL.search(text)
    if not m:
        return "other"
    goal, msg = m.groups()
    if "counter-maven-plugin" in goal:
        return "plugin"
    if "maven-compiler" in goal:
        return "compile"
    if "surefire" in goal or "failsafe" in goal:
        return "tests"
    if RESOLVE_MSG.search(msg):
        return "resolution"
    return "other"


# def repo_of_log(stem, known):
#     for r in sorted(known, key=len, reverse=True):
#         if stem.startswith(r + "_"):
#             return r
#     return stem.split("_")[0]


def drop_flavor_named(df):
    """Rows named after a flavor folder come from an old collector bug (repo = buildcache.parent.name)."""
    bad = df["repo"].astype(str).str.match(r"^(RQ\d.*|base)$")
    if bad.any():
        print(f"[WARN] ignoring {int(bad.sum())} row(s) whose repo name is a flavor folder; rerun the collectors",
              file=sys.stderr)
    return df[~bad]


def pass_rate(passed, total, skipped=None):
    den = total - skipped if (PASS_RATE_EXCLUDES_SKIPPED and skipped is not None) else total
    return passed, den, np.where(den > 0, passed / den * 100, np.nan)


def load_flag(root, flag):
    res = root / "results"

    mods = read(res / f"rq2_results_{flag}.csv")
    deps = None
    if mods is not None:
        mods = drop_flavor_named(mods)
        cols = [c for c in ACTIONS + ["total_before", "total_after"] if c in mods.columns]
        deps = mods.groupby("repo")[cols].sum()
        deps["modules"] = mods.groupby("repo").size()
        deps = deps.reset_index()

    tests = read(res / f"rq1_style_stats_{flag}.csv")
    if tests is not None:
        tests = drop_flavor_named(tests)
        skipped = tests["total_skipped"] if "total_skipped" in tests else None
        passed, den, rate = pass_rate(tests["total_passed"], tests["total_tests"], skipped)
        tests = pd.DataFrame({"repo": tests["repo"], "tests_passed": passed, "tests_den": den,
                              "pass_rate": rate, "stats_build_ok": tests["build_success"].astype(bool)})

    repos = set()
    for d in (deps, tests):
        if d is not None:
            repos |= set(d["repo"])
    df = pd.DataFrame({"repo": sorted(repos)})
    df["flag"] = flag
    for d in (deps, tests):
        if d is not None:
            df = df.merge(d, on="repo", how="left")

    df["built"] = df["stats_build_ok"].fillna(False).astype(bool) if "stats_build_ok" in df else False
    return df, mods


def load_baseline(root):
    df = read(root / "results" / "rq1_results.csv")
    if df is None:
        return None
    df = drop_flavor_named(df)
    skipped = df["total_skipped"] if "total_skipped" in df else None
    _, _, rate = pass_rate(df["total_passed"], df["total_tests"], skipped)
    out = pd.DataFrame({"repo": df["repo"], "rq1_pass_rate": rate})
    if "build_success" in df:
        out["rq1_built"] = df["build_success"].astype(bool)
    else:
        print("[WARN] rq1_results.csv has no build_success column; RQ1 failures cannot be excluded",
              file=sys.stderr)
        out["rq1_built"] = True
    out.loc[~out["rq1_built"], "rq1_pass_rate"] = np.nan
    if "upgraded_count" in df:
        out["rq1_upgraded"] = df["upgraded_count"].where(out["rq1_built"])
    return out


def diagnostics(root, mods_by_flag):
    res = root / "results"
    stats = {f: read(res / f"rq1_style_stats_{f}.csv") for f in FLAGS}
    stats = {f: d for f, d in stats.items() if d is not None}
    for a, b in combinations(stats, 2):
        if stats[a].reset_index(drop=True).equals(stats[b].reset_index(drop=True)):
            print(f"[WARN] rq1_style_stats_{a}.csv and rq1_style_stats_{b}.csv are identical. The RQ2 pipeline is "
                  f"probably reading the RQ1 checkouts for test numbers; test results will look the same for every flag.",
                  file=sys.stderr)
    for f, m in mods_by_flag.items():
        if m is not None and "build_success" in m and m["build_success"].astype(bool).all():
            print(f"[NOTE] rq2_results_{f}.csv has build_success=True on every row; it is ignored "
                  f"(build status is read from rq1_style_stats_{f}.csv).", file=sys.stderr)


# ------------------------------------------------------------------------------ helpers

def pivot(tidy, col, repos):
    return tidy.pivot(index="repo", columns="flag", values=col).reindex(index=repos, columns=FLAGS)


def save(fig, out, name):
    fig.tight_layout()
    fig.savefig(out / name, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}")


def label_missing(ax, matrix, labels):
    """seaborn leaves NaN cells blank even when annotations are given; draw the label ourselves."""
    ax.grid(False)
    for i, r in enumerate(matrix.index):
        for j, c in enumerate(matrix.columns):
            if pd.isna(matrix.loc[r, c]):
                ax.text(j + 0.5, i + 0.5, labels.loc[r, c], ha="center", va="center", fontsize=10, color="#555555")


def pareto_max(points):
    """Points not dominated when BOTH coordinates are maximised."""
    pts = np.asarray(points, dtype=float)
    keep = np.ones(len(pts), dtype=bool)
    for i, p in enumerate(pts):
        keep[i] = not np.any(np.all(pts >= p, axis=1) & np.any(pts > p, axis=1))
    return pts[keep]


# ------------------------------------------------------------------------------ graphs

def g_upgrades_by_repo(tidy, repos, out):
    up = pivot(tidy, "upgraded", repos)
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    y, h = np.arange(len(repos)), 0.26
    fig, ax = plt.subplots(figsize=(11, max(7, len(repos) * 0.5)))
    for i, flag in enumerate(FLAGS):
        vals = up[flag].fillna(0)
        bars = ax.barh(y + (i - 1) * h, vals, h, label=flag.capitalize(), color=COLORS[flag])
        ax.bar_label(bars, labels=[f"{int(v)}" if b else f"{int(v)} ✗" for v, b in zip(vals, built[flag])],
                     padding=3, fontsize=7)
    ax.set_yticks(y)
    ax.set_yticklabels(repos, fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlabel("Upgraded dependencies (summed over modules)   ✗ = build failed", fontweight="bold")
    ax.set_title("Dependency Upgrades by Repository and Flag (RQ2)", fontweight="bold", pad=15)
    ax.legend(loc="lower right", frameon=True)
    tot = up.sum()
    ax.text(0.02, 0.98, "Totals:  " + "   ".join(f"{f.capitalize()} {int(tot[f])}" for f in FLAGS),
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9, edgecolor="#ccc"))
    save(fig, out, "rq2_repo_dependency_breakdown.png")


def g_upgrade_pct_heatmap(tidy, repos, out):
    pct = pivot(tidy, "upgraded_pct", repos)
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    labels = pct.copy().astype(object)
    for r in repos:
        for f in FLAGS:
            v = pct.loc[r, f]
            labels.loc[r, f] = ("✗" if not built.loc[r, f] else "n/a") if pd.isna(v) \
                else (f"{v:.0f}%" + ("" if built.loc[r, f] else " ✗"))
    fig, ax = plt.subplots(figsize=(6.5, max(5, len(repos) * 0.42)))
    ax.set_facecolor("#dddddd")
    sns.heatmap(pct, annot=labels.where(pct.notna(), "").values, fmt="", cmap="YlOrRd",
                cbar_kws={"label": "% of dependencies upgraded"}, linewidths=0.5, linecolor="white", ax=ax)
    label_missing(ax, pct, labels)
    ax.set_xticklabels([f.capitalize() for f in FLAGS])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("Share of Dependencies Upgraded   (✗ = build failed)", fontweight="bold", pad=12)
    save(fig, out, "rq2_upgrade_share_heatmap.png")


def g_action_averages(mods_by_flag, out):
    rows = []
    for f, m in mods_by_flag.items():
        if m is not None and len(m):
            for a in ACTIONS:
                if a in m:
                    rows.append({"flag": f, "action": a.replace("_", " ").capitalize(), "avg": m[a].mean()})
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.barplot(data=pd.DataFrame(rows), x="flag", y="avg", hue="action", order=[f for f in FLAGS if f in mods_by_flag],
                palette="muted", ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.2f", padding=2, fontsize=7)
    ax.set_xlabel("Update flag", fontweight="bold")
    ax.set_ylabel("Average per module", fontweight="bold")
    ax.set_title("Average Dependency Changes per Module", fontweight="bold", pad=15)
    ax.legend(title="Change", loc="upper left", bbox_to_anchor=(1.02, 1.0))
    save(fig, out, "rq2_flag_action_comparison.png")


def g_test_success_by_repo(tidy, repos, out):
    series = {"RQ1": tidy.drop_duplicates("repo").set_index("repo").reindex(repos)["rq1_pass_rate"]
              if "rq1_pass_rate" in tidy else None}
    series.update({f: pivot(tidy, "pass_rate", repos)[f] for f in FLAGS})
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    series = {k: v for k, v in series.items() if v is not None}
    keys = list(series)
    y, h = np.arange(len(repos)), 0.8 / len(keys)
    fig, ax = plt.subplots(figsize=(11, max(7, len(repos) * 0.55)))
    for i, k in enumerate(keys):
        vals = series[k]
        mean = vals.mean()
        bars = ax.barh(y + (i - (len(keys) - 1) / 2) * h, vals.fillna(0), h, color=COLORS[k],
                       label=f"{k.capitalize() if k != 'RQ1' else 'RQ1'} (mean {mean:.1f}%)")
        labels = []
        for r, v in zip(repos, vals):
            if not pd.isna(v):
                labels.append(f"{v:.1f}%")
            else:
                ok = tidy.loc[tidy["repo"] == r, "rq1_built" if k == "RQ1" else "built"]
                if k != "RQ1":
                    ok = built.loc[r, k]
                else:
                    ok = bool(ok.iloc[0]) if len(ok) else False
                labels.append("no tests" if ok else "build failed")
        ax.bar_label(bars, labels=labels, padding=3, fontsize=6)
    ax.set_yticks(y)
    ax.set_yticklabels(repos, fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlim(0, 125)
    ax.set_xlabel("Test pass rate (%) — failed builds excluded", fontweight="bold")
    ax.set_title("Test Success by Repository: RQ1 vs RQ2", fontweight="bold", pad=15)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=True)
    save(fig, out, "rq2_test_success_rate.png")


def g_test_strip(tidy, repos, out):
    parts = [tidy[tidy["built"]][["repo", "flag", "pass_rate"]]]
    if "rq1_pass_rate" in tidy:
        b = tidy.drop_duplicates("repo")[["repo", "rq1_pass_rate"]].rename(columns={"rq1_pass_rate": "pass_rate"})
        b["flag"] = "RQ1"
        parts.append(b)
    d = pd.concat(parts).dropna(subset=["pass_rate"])
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 6))
    order = [k for k in ["RQ1"] + FLAGS if k in set(d["flag"])]
    sns.stripplot(data=d, x="repo", y="pass_rate", hue="flag", hue_order=order, order=repos,
                  palette=COLORS, dodge=True, jitter=0.15, size=7, ax=ax)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("Repository", fontweight="bold")
    ax.set_ylabel("Test pass rate (%)", fontweight="bold")
    ax.set_title("Test Pass Rate per Repository (built repositories only)", fontweight="bold", pad=15)
    ax.legend(title="Scope", loc="lower left")
    save(fig, out, "rq2_test_success_scatter.png")


def g_macro(tidy, out):
    rows = []
    for f in FLAGS:
        t = tidy[tidy["flag"] == f]
        if t.empty:
            continue
        rows.append({"flag": f.capitalize(), "build": t["built"].mean() * 100,
                     "tests": t["pass_rate"].mean(),                 # all repos, no tests / failed = 0
                     "upg": t["upgrades_per_module"].mean()})        # repos with >= 1 module
            

    d = pd.DataFrame(rows)
    if d.empty:
        return
    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = np.arange(len(d))
    l1 = ax1.plot(x, d["build"], color="#4c72b0", marker="s", lw=2.5, ms=8, label="Repos that build (%)")
    l2 = ax1.plot(x, d["tests"], color="#55a868", marker="^", lw=2.5, ms=8, label="Tests passing, built repos (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(d["flag"])
    ax1.set_ylim(0, 108)
    ax1.set_xlabel("Update flag", fontweight="bold")
    ax1.set_ylabel("Rate (%)", fontweight="bold")
    ax2 = ax1.twinx()
    l3 = ax2.plot(x, d["upg"], color="#c44e52", marker="o", lw=2.5, ms=8, ls="--", label="Avg upgraded deps / module")
    ax2.set_ylabel("Upgraded dependencies per module", fontweight="bold", color="#c44e52")
    ax2.tick_params(axis="y", labelcolor="#c44e52")
    ax2.grid(False)
    for i, r in d.iterrows():
        ax1.text(i, r["build"] + 2, f"{r['build']:.1f}%", color="#4c72b0", fontweight="bold", ha="center")
        if not pd.isna(r["tests"]):
            ax1.text(i, r["tests"] - 6, f"{r['tests']:.1f}%", color="#55a868", fontweight="bold", ha="center")
        if not pd.isna(r["upg"]):
            ax2.text(i, r["upg"] + 0.1, f"{r['upg']:.2f}", color="#c44e52", fontweight="bold", ha="center")
    lines = l1 + l2 + l3
    ax1.legend(lines, [l.get_label() for l in lines], loc="upper left", bbox_to_anchor=(1.15, 1.0))
    ax1.set_title("Build/Test Success vs. Upgraded Dependencies by Flag", fontweight="bold", pad=15)
    save(fig, out, "rq2_dual_axis_success_vs_upgrades.png")


def g_upgrades_vs_tests(tidy, out):
    d = tidy[tidy["built"]].dropna(subset=["pass_rate", "upgraded_pct"])
    if d.empty:
        return
    panels = [("pass_rate", "Test pass rate (%)")]
    if "pass_delta" in d and d["pass_delta"].notna().any():
        panels.append(("pass_delta", "Change in pass rate vs RQ1 (percentage points)"))
    fig, axes = plt.subplots(1, len(panels), figsize=(7.5 * len(panels), 6), squeeze=False)
    for ax, (col, label) in zip(axes[0], panels):
        dd = d.dropna(subset=[col])
        sns.scatterplot(data=dd, x="upgraded_pct", y=col, hue="flag", style="flag", hue_order=FLAGS,
                        palette=COLORS, s=90, alpha=0.85, ax=ax)
        if col == "pass_delta":
            ax.axhline(0, color="black", lw=1)
        # label the interesting points: biggest drops and most upgraded
        ref = dd[col].sort_values().index[:3].tolist() + dd["upgraded_pct"].sort_values().index[-2:].tolist()
        for i in dict.fromkeys(ref):
            ax.annotate(dd.loc[i, "repo"], (dd.loc[i, "upgraded_pct"], dd.loc[i, col]), fontsize=7,
                        xytext=(5, 5), textcoords="offset points")
        notes = []
        if len(dd) >= 4:
            notes.append(f"Spearman ρ (all) = {dd['upgraded_pct'].corr(dd[col], method='spearman'):.2f}   n={len(dd)}")
        ax.text(0.02, 0.02, "\n".join(notes), transform=ax.transAxes, fontsize=8,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.9, edgecolor="#ccc"))
        ax.set_xlabel("Dependencies upgraded (% of all resolved dependencies in the repository)", fontweight="bold")
        ax.set_ylabel(label, fontweight="bold")
        ax.legend(title="Flag")
    fig.suptitle("Do More Upgrades Mean Fewer Passing Tests?  (one point per repository, built repos only)",
                 fontweight="bold")
    save(fig, out, "rq2_upgrades_vs_test_success.png")


def g_delta_heatmap(tidy, repos, out):
    if "pass_delta" not in tidy or tidy["pass_delta"].notna().sum() == 0:
        return
    delta = pivot(tidy, "pass_delta", repos)
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    labels = delta.copy().astype(object)
    for r in repos:
        for f in FLAGS:
            v = delta.loc[r, f]
            labels.loc[r, f] = f"{v:+.1f}" if not pd.isna(v) else ("n/a" if built.loc[r, f] else "✗")
    lim = max(1.0, float(np.nanmax(np.abs(delta.values))))
    fig, ax = plt.subplots(figsize=(6.5, max(5, len(repos) * 0.42)))
    ax.set_facecolor("#dddddd")
    sns.heatmap(delta, annot=labels.where(delta.notna(), "").values, fmt="", cmap="RdBu", center=0,
                vmin=-lim, vmax=lim, cbar_kws={"label": "pass rate vs RQ1 (percentage points)"},
                linewidths=0.5, linecolor="white", ax=ax)
    label_missing(ax, delta, labels)
    ax.set_xticklabels([f.capitalize() for f in FLAGS])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("Test Pass Rate Change vs RQ1   (✗ = build failed)", fontweight="bold", pad=12)
    save(fig, out, "rq2_test_delta_vs_rq1_heatmap.png")


def g_pareto(root, out, built_repos):
    parts = []
    for f in FLAGS:
        d = read(root / "results" / f"rq1_style_stats_{f}_modules.csv")
        if d is not None and {"upgraded", "pass_rate"} <= set(d.columns):
            d = drop_flavor_named(d)
            d = d[d["repo"].isin(built_repos[f])]
            d["flag"] = f
            parts.append(d)
    if not parts:
        return
    d = pd.concat(parts, ignore_index=True)
    d["pass_rate"] = pd.to_numeric(d["pass_rate"], errors="coerce")
    d = d.dropna(subset=["pass_rate", "upgraded"])
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.scatterplot(data=d, x="upgraded", y="pass_rate", hue="flag", style="flag", hue_order=FLAGS,
                    palette=COLORS, alpha=0.65, s=60, ax=ax)
    front = pareto_max(d[["upgraded", "pass_rate"]].drop_duplicates().values)
    front = front[front[:, 0].argsort()]
    ax.plot(front[:, 0], front[:, 1], color="black", ls="--", lw=1.5, marker="o", ms=4,
            label="Pareto front (more upgrades, higher pass rate)")
    ax.set_xlabel("Upgraded dependencies in module", fontweight="bold")
    ax.set_ylabel("Module test pass rate (%)", fontweight="bold")
    ax.set_title("Trade-off per Module: Upgrades vs Test Pass Rate", fontweight="bold")
    ax.legend(loc="lower left")
    save(fig, out, "rq2_pareto_upgrades_vs_passrate.png")


def g_box(mods_by_flag, out):
    parts = []
    for f, m in mods_by_flag.items():
        if m is not None and len(m):
            parts.append(pd.DataFrame({"flag": f, "upgraded": m["upgraded"]}))
    if not parts:
        return
    d = pd.concat(parts)
    order = [f for f in FLAGS if f in set(d["flag"])]
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(data=d, x="flag", y="upgraded", order=order, hue="flag", palette=COLORS, legend=False,
                showmeans=True, meanprops=dict(marker="o", markerfacecolor="white", markeredgecolor="black"),
                fliersize=0, ax=ax)
    sns.stripplot(data=d, x="flag", y="upgraded", order=order, color="black", size=2.5, alpha=0.35, ax=ax)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f.capitalize() for f in order])
    ax.set_title("Upgraded Dependencies per Module (symlog scale, dots = modules)", fontweight="bold")
    ax.set_xlabel("Update flag", fontweight="bold")
    ax.set_ylabel("Upgraded dependencies", fontweight="bold")
    save(fig, out, "rq2_upgraded_distribution_box.png")


# ------------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root (default: cwd)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "graphs")
    ap.add_argument("--exclude", nargs="*", default=[], help="repositories to leave out of every graph")
    a = ap.parse_args()
    root, out = a.root.resolve(), a.out
    out.mkdir(parents=True, exist_ok=True)

    frames, mods_by_flag = [], {}
    for f in FLAGS:
        df, mods = load_flag(root, f)
        frames.append(df)
        mods_by_flag[f] = mods

    tidy = pd.concat(frames, ignore_index=True)
    tidy = tidy[~tidy["repo"].isin(a.exclude)].drop_duplicates(["repo", "flag"])
    mods_by_flag = {f: (m[~m["repo"].isin(a.exclude)] if m is not None else None) for f, m in mods_by_flag.items()}

    for col in ACTIONS + ["total_before", "total_after"]:
        if col not in tidy:
            tidy[col] = np.nan
    tidy["upgraded_pct"] = np.where(tidy["total_before"] > 0, tidy["upgraded"] / tidy["total_before"] * 100, np.nan)
    tidy["upgrades_per_module"] = np.where(tidy["modules"] > 0, tidy["upgraded"] / tidy["modules"], np.nan)

    base = load_baseline(root)
    if base is not None:
        tidy = tidy.merge(base, on="repo", how="left")
        tidy["rq1_built"] = tidy["rq1_built"].fillna(False).astype(bool)
        tidy["pass_delta"] = tidy["pass_rate"] - tidy["rq1_pass_rate"]
        if "rq1_upgraded" in tidy:
            tidy["net_upgraded"] = tidy["upgraded"] - tidy["rq1_upgraded"]

    flag_metrics = [c for c in ACTIONS + ["total_before", "total_after", "modules", "tests_passed", "tests_den",
                                          "pass_rate", "upgraded_pct", "upgrades_per_module",
                                          "pass_delta", "net_upgraded"] if c in tidy]
    tidy.loc[~tidy["built"], flag_metrics] = np.nan

    built_repos = {f: set(tidy[(tidy["flag"] == f) & tidy["built"]]["repo"]) for f in FLAGS}
    mods_built = {f: (m[m["repo"].isin(built_repos[f])] if m is not None else None)
                  for f, m in mods_by_flag.items()}

    diagnostics(root, mods_by_flag)
    repos = sorted(tidy["repo"].unique())
    if not repos:
        print("No data found; have the RQ2 pipelines been run?")
        return
    table = root / "results" / "rq2_repo_flag_table.csv"
    tidy.sort_values(["repo", "flag"]).to_csv(table, index=False)
    print(f"{len(repos)} repositories; table written to {table}")

    g_upgrades_by_repo(tidy, repos, out)
    g_upgrade_pct_heatmap(tidy, repos, out)
    g_action_averages(mods_built, out)
    g_test_success_by_repo(tidy, repos, out)
    g_test_strip(tidy, repos, out)
    g_macro(tidy, out)
    g_upgrades_vs_tests(tidy, out)
    g_delta_heatmap(tidy, repos, out)
    g_pareto(root, out, built_repos)
    g_box(mods_built, out)



if __name__ == "__main__":
    main()