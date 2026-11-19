#!/usr/bin/env python3
"""
graph_rq2.py — Unified graphing script for RQ2 and Base range comparisons.

Run from the reproducible-central root:
    python3 scripts/graph_rq2.py --mode rq2
    python3 scripts/graph_rq2.py --mode base_range    (alias: base)

Inputs per mode (all in results/; <mode> is literally rq2 or base_range):
    <mode>_results_<flag>.csv         module rows of the collector
    <mode>_results_<flag>_repos.csv   optional repo-level table; if it has repo + build_success it decides "built"
    test stats: <mode>_rq1_style_stats_<flag>.csv, falling back to rq1_style_stats_<flag>.csv (rq2) /
                base_rq1_style_stats_<flag>.csv (base_range)
    rq1_results.csv                   RQ1 baseline

Version jumps need the collector to be run with --lag. Without it the "jump" graphs fall back to the plain
upgraded-dependency count (and say so), instead of drawing zeros.
"""

import argparse
import sys
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

LAG_COLUMNS = [
    "lag_deps", "lag_days_deps", "lag_days_before", "lag_days_after", "lag_days_reduction",
    "behind_before", "behind_after", "behind_reduction",
    "stale_major_before", "stale_minor_before", "stale_patch_before",
    "stale_major_after", "stale_minor_after", "stale_patch_after",
    "lag_unknown", "not_at_policy_latest", "versions_jumped"
]

PASS_RATE_EXCLUDES_SKIPPED = False

# what the "jump" graphs plot; set in main() depending on whether the collector measured versions_jumped
METRIC_COL = "versions_jumped"
METRIC_NAME = "Versions jumped"

# ------------------------------------------------------------------------------ naming per mode

def files_for(mode):
    """mode is literally 'rq2' or 'base_range', matching the collector's {mode}_results_{flag}.csv."""
    stats = [f"{mode}_rq1_style_stats_{{flag}}.csv"]
    stats += ["rq1_style_stats_{flag}.csv"] if mode == "rq2" else ["base_rq1_style_stats_{flag}.csv"]
    return dict(results=f"{mode}_results_{{flag}}.csv",
                repos=f"{mode}_results_{{flag}}_repos.csv",
                stats=stats,
                modules=[t.replace(".csv", "_modules.csv") for t in stats])


def find_first(res, templates, flag):
    for t in templates:
        p = res / t.format(flag=flag)
        if p.exists():
            return p
    return None


# ------------------------------------------------------------------------------ loading

def read(path):
    return pd.read_csv(path) if path.exists() else None


def drop_flavor_named(df):
    if "repo" not in df.columns:
        return df
    bad = df["repo"].astype(str).str.match(r"^(RQ\d.*|base|base(Major|Minor|Patch))$")
    return df[~bad]


def as_bool(series):
    return series.astype(str).str.lower().eq("true")


def sum_keep_nan(s):
    return s.sum(min_count=1)       # all-NaN stays NaN (e.g. lag columns when --lag was not used)

def _mode_prefix(mode: str) -> str:
    if mode in ("base_range", "base"):
        return "base_range"
    return "rq2"


def load_flag(root, mode, flag):
    """Module-level dependency results of one flag, aggregated to one row per repo."""
    res = Path(root) / "results"
    prefix = _mode_prefix(mode)

    csv_path = res / f"{prefix}_results_{flag}.csv"
    mods = read(csv_path)
    if mods is None:
        print(f"[WARN] Could not find expected results file: {csv_path}", file=sys.stderr)
        return pd.DataFrame(), None

    mods = drop_flavor_named(mods)

    # counts that are always present: missing -> 0. Lag columns are only present with --lag: missing -> NaN.
    for col in ACTIONS + ["total_before", "total_after", "build_time_s"]:
        mods[col] = pd.to_numeric(mods[col], errors="coerce").fillna(0.0) if col in mods.columns else 0.0
    for col in LAG_COLUMNS:
        mods[col] = pd.to_numeric(mods[col], errors="coerce") if col in mods.columns else np.nan

    mods["built"] = as_bool(mods["build_success"]) if "build_success" in mods.columns else True

    placeholder = (mods["module"] == "<no-report>") if "module" in mods.columns else pd.Series(False, index=mods.index)
    mods["modules"] = (~placeholder).astype(int)  # placeholder rows are failed repos, not modules
    mods["upgraded_pct"] = np.where(mods["total_before"] > 0, mods["upgraded"] / mods["total_before"] * 100, 0.0)
    mods.loc[placeholder, "upgraded_pct"] = np.nan

    agg = {"built": "max", "build_time_s": "mean", "modules": "sum", "upgraded_pct": "mean"}
    for c in ACTIONS + ["total_before", "total_after"]:
        agg[c] = "sum"
    for c in LAG_COLUMNS:
        agg[c] = sum_keep_nan

    df = mods.groupby("repo").agg(agg).reset_index()
    df["flag"] = flag

    # repo-level table (includes repos without any comparison report): authoritative for "built"
    repos_candidates = [
        res / f"{prefix}_results_{flag}_repos.csv",
        res / f"{prefix}_repos_{flag}.csv",
    ]
    repos_path = next((p for p in repos_candidates if p.exists()), None)
    rtab = read(repos_path) if repos_path else None
    if rtab is not None and {"repo", "build_success"} <= set(rtab.columns):
        rtab = drop_flavor_named(rtab)
        rb = rtab.assign(built_repos=as_bool(rtab["build_success"]))[["repo", "built_repos"]].drop_duplicates("repo")
        df = df.merge(rb, on="repo", how="outer")
        df["flag"] = flag
        disagree = df["built_repos"].notna() & df["built"].notna() & (df["built_repos"] != df["built"].astype(bool))
        if disagree.any():
            print(f"[NOTE] {flag}: {repos_path.name} and the module CSV disagree on build status for "
                  f"{int(disagree.sum())} repo(s); using {repos_path.name}.", file=sys.stderr)
        df["built"] = df["built_repos"].where(df["built_repos"].notna(), df["built"]).fillna(False).astype(bool)
        for c in ["modules"] + ACTIONS + ["total_before", "total_after"]:
            df[c] = df[c].fillna(0)
        df = df.drop(columns="built_repos")

    # test numbers (from collect_rq1_results.py)
    stats_candidates = [
        res / f"rq1_style_stats_{prefix}_{flag}.csv",
        res / f"rq1_style_stats_{flag}.csv",
    ]
    stats_path = next((p for p in stats_candidates if p.exists()), None)
    tests = read(stats_path) if stats_path else None
    if tests is not None:
        tests = drop_flavor_named(tests)
        if {"total_passed", "total_tests"} <= set(tests.columns):
            den = pd.to_numeric(tests["total_tests"], errors="coerce")
            passed = pd.to_numeric(tests["total_passed"], errors="coerce")
            if PASS_RATE_EXCLUDES_SKIPPED and "total_skipped" in tests:
                den = den - pd.to_numeric(tests["total_skipped"], errors="coerce").fillna(0)
            rate = np.where(den > 0, passed / den * 100, np.nan)
            repo_rates = (
                pd.DataFrame({"repo": tests["repo"], "pass_rate": rate})
                .groupby("repo", as_index=False)["pass_rate"]
                .mean()
            )
            df = df.merge(repo_rates, on="repo", how="left")

    return df, mods

def load_baseline(root):
    df = read(root / "results" / "rq1_results.csv")
    if df is None:
        return None
    df = drop_flavor_named(df)
    skipped = df["total_skipped"] if "total_skipped" in df else None

    if "total_passed" in df.columns and "total_tests" in df.columns:
        den = df["total_tests"] - skipped if (PASS_RATE_EXCLUDES_SKIPPED and skipped is not None) else df["total_tests"]
        rate = np.where(den > 0, df["total_passed"] / den * 100, np.nan)
    else:
        rate = np.nan

    out = pd.DataFrame({"repo": df["repo"], "rq1_pass_rate": rate})
    out["rq1_built"] = as_bool(df["build_success"]) if "build_success" in df else True
    out.loc[~out["rq1_built"], "rq1_pass_rate"] = np.nan
    if "upgraded_count" in df:
        out["rq1_upgraded"] = df["upgraded_count"].where(out["rq1_built"])
    return out


def diagnostics(root, mods_by_flag):
    for f, m in mods_by_flag.items():
        if m is not None and "build_success" in m and as_bool(m["build_success"]).all():
            print(f"[NOTE] {f}: build_success=True on every row.", file=sys.stderr)


# ------------------------------------------------------------------------------ helpers

def pivot(tidy, col, repos):
    return tidy.pivot(index="repo", columns="flag", values=col).reindex(index=repos, columns=FLAGS)


def save(fig, out, name):
    fig.tight_layout()
    fig.savefig(out / name, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"   wrote {name}")


def label_missing(ax, matrix, labels):
    ax.grid(False)
    for i, r in enumerate(matrix.index):
        for j, c in enumerate(matrix.columns):
            if pd.isna(matrix.loc[r, c]):
                ax.text(j + 0.5, i + 0.5, labels.loc[r, c], ha="center", va="center", fontsize=10, color="#555555")


def pareto_max(points):
    pts = np.asarray(points, dtype=float)
    keep = np.ones(len(pts), dtype=bool)
    for i, p in enumerate(pts):
        keep[i] = not np.any(np.all(pts >= p, axis=1) & np.any(pts > p, axis=1))
    return pts[keep]


# ------------------------------------------------------------------------------ graphs

def g_upgrades_by_repo(tidy, repos, mode, out):
    up = pivot(tidy, METRIC_COL, repos)
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
    ax.set_xlabel(f"{METRIC_NAME} (summed over modules)   ✗ = build failed", fontweight="bold")
    ax.set_title(f"{METRIC_NAME} by Repository and Flag ({mode.upper()})", fontweight="bold", pad=15)
    ax.legend(loc="lower right", frameon=True)
    tot = up.sum()
    ax.text(0.02, 0.98, "Totals:  " + "   ".join(f"{f.capitalize()} {int(tot[f])}" for f in FLAGS),
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9, edgecolor="#ccc"))
    save(fig, out, f"{mode}_repo_dependency_breakdown.png")


def g_upgrade_pct_heatmap(tidy, repos, mode, out):
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
    ax.set_title(f"Share of Dependencies Upgraded ({mode.upper()})   (✗ = build failed)", fontweight="bold", pad=12)
    save(fig, out, f"{mode}_upgrade_share_heatmap.png")


def g_action_averages(mods_by_flag, mode, out):
    rows = []
    for f, m in mods_by_flag.items():
        if m is not None and len(m):
            m = m[m["modules"] > 0]
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
    ax.set_title(f"Average Dependency Changes per Module ({mode.upper()})", fontweight="bold", pad=15)
    ax.legend(title="Change", loc="upper left", bbox_to_anchor=(1.02, 1.0))
    save(fig, out, f"{mode}_flag_action_comparison.png")


def g_test_success_by_repo(tidy, repos, mode, out):
    if "pass_rate" not in tidy.columns:
        return
    series = {"RQ1": tidy.drop_duplicates("repo").set_index("repo").reindex(repos)["rq1_pass_rate"]
              if "rq1_pass_rate" in tidy else None}
    series.update({f: pivot(tidy, "pass_rate", repos)[f] for f in FLAGS})
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    rq1_built = (tidy.drop_duplicates("repo").set_index("repo").reindex(repos)["rq1_built"].fillna(False).astype(bool)
                 if "rq1_built" in tidy else pd.Series(False, index=repos))
    series = {k: v for k, v in series.items() if v is not None}
    keys = list(series)
    if not keys:
        return
    y, h = np.arange(len(repos)), 0.8 / len(keys)
    fig, ax = plt.subplots(figsize=(11, max(7, len(repos) * 0.55)))
    for i, k in enumerate(keys):
        vals = series[k]
        mean = vals.mean()
        bars = ax.barh(y + (i - (len(keys) - 1) / 2) * h, vals.fillna(0), h, color=COLORS.get(k, "#333333"),
                       label=f"{k.capitalize() if k != 'RQ1' else 'RQ1'} (mean {mean:.1f}%)")
        labels = []
        for r, v in zip(repos, vals):
            if not pd.isna(v):
                labels.append(f"{v:.1f}%")
            else:
                ok = rq1_built.loc[r] if k == "RQ1" else built.loc[r, k]
                labels.append("no tests" if ok else "build failed")
        ax.bar_label(bars, labels=labels, padding=3, fontsize=6)
    ax.set_yticks(y)
    ax.set_yticklabels(repos, fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlim(0, 125)
    ax.set_xlabel("Test pass rate (%) — failed builds excluded", fontweight="bold")
    ax.set_title(f"Test Success by Repository: RQ1 vs {mode.upper()}", fontweight="bold", pad=15)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=True)
    save(fig, out, f"{mode}_test_success_rate.png")


def g_test_strip(tidy, repos, mode, out):
    if "pass_rate" not in tidy.columns:
        return
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
    ax.set_title(f"Test Pass Rate per Repository ({mode.upper()}, built repositories only)", fontweight="bold", pad=15)
    ax.legend(title="Scope", loc="lower left")
    save(fig, out, f"{mode}_test_success_scatter.png")


METRIC_COL = "versions_jumped"
METRIC_NAME = "Version Jumps"

def g_macro(tidy, mode, out):
    """Build Success Rate, Test Pass Rate, and Average Metric per Module by Flag."""
    rows = []
    for f in FLAGS:
        t = tidy[tidy["flag"] == f]
        if t.empty:
            continue
            
        built_mask = t["built"].astype(bool)
        build_rate = built_mask.mean() * 100
        test_rate = t[built_mask]["pass_rate"].mean() if "pass_rate" in t.columns and built_mask.any() else np.nan
        
        total = t[METRIC_COL].fillna(0).sum() if METRIC_COL in t.columns else 0
        modules = t["modules"].fillna(0).sum() if "modules" in t.columns else len(t)
        metric_val = total / modules if modules > 0 else 0
        
        rows.append({
            "flag": f.capitalize(),
            "build": build_rate,
            "tests": test_rate,
            "metric": metric_val,
            "n": len(t)
        })

    d = pd.DataFrame(rows)
    if d.empty:
        return
        
    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = np.arange(len(d))
    
    # Left axis lines: Build Rate & Test Pass Rate
    l1 = ax1.plot(x, d["build"], color="#4c72b0", marker="s", lw=2.5, ms=8, label="Repos that build (%)")
    lines = l1
    
    if "tests" in d.columns and d["tests"].notna().any():
        l2 = ax1.plot(x, d["tests"], color="#55a868", marker="^", lw=2.5, ms=8, label="Tests passing, built repos (%)")
        lines = lines + l2
        
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{r.flag}\n(n={r.n})" for r in d.itertuples()])
    ax1.set_ylim(0, 108)
    ax1.set_xlabel("Update flag", fontweight="bold")
    ax1.set_ylabel("Rate (%)", fontweight="bold")

    # Right axis line: Average Metric / Version Jumps
    ax2 = ax1.twinx()
    l3 = ax2.plot(x, d["metric"], color="#c44e52", marker="o", lw=2.5, ms=8, ls="--",
                  label=f"Avg {METRIC_NAME.lower()} / module (incl. failed repos)")
    ax2.set_ylabel(f"Average {METRIC_NAME.lower()} per module", fontweight="bold", color="#c44e52")
    ax2.tick_params(axis="y", labelcolor="#c44e52")
    ax2.grid(False)

    # Numerical labels on data points
    for i, r in d.iterrows():
        ax1.text(i, r["build"] + 2, f"{r['build']:.1f}%", color="#4c72b0", fontweight="bold", ha="center")
        if not pd.isna(r["tests"]):
            ax1.text(i, r["tests"] - 6, f"{r['tests']:.1f}%", color="#55a868", fontweight="bold", ha="center")
        if not pd.isna(r["metric"]):
            ax2.text(i, r["metric"] + 0.1, f"{r['metric']:.2f}", color="#c44e52", fontweight="bold", ha="center")

    lines = lines + l3
    ax1.legend(
    lines, [l.get_label() for l in lines],
    loc="lower center",
    ncol=1,
    fontsize=9,
    framealpha=0.9,
)
    ax1.set_title(f"Build Success, Test Pass Rate & {METRIC_NAME} ({mode.upper()})", fontweight="bold", pad=15)
    save(fig, out, f"{mode}_dual_axis_success_vs_upgrades.png")


def g_upgrades_vs_tests(tidy, mode, out):
    if "pass_rate" not in tidy.columns:
        return
    d = tidy[tidy["built"]].dropna(subset=["pass_rate", METRIC_COL])
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.scatterplot(data=d, x=METRIC_COL, y="pass_rate", hue="flag", style="flag", hue_order=FLAGS,
                    palette=COLORS, s=90, alpha=0.85, ax=ax)
    ax.set_xlabel(METRIC_NAME, fontweight="bold")
    ax.set_ylabel("Test Pass Rate (%)", fontweight="bold")
    ax.set_title(f"Do More Upgrades Mean Fewer Passing Tests? ({mode.upper()})", fontweight="bold")
    save(fig, out, f"{mode}_upgrades_vs_test_success.png")


def g_delta_heatmap(tidy, repos, mode, out):
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
    ax.set_title(f"Test Pass Rate Change vs RQ1 ({mode.upper()})   (✗ = build failed)", fontweight="bold", pad=12)
    save(fig, out, f"{mode}_test_delta_vs_rq1_heatmap.png")


def g_pareto(root, mode, out, built_repos):
    parts = []
    for f in FLAGS:
        mp = find_first(root / "results", files_for(mode)["modules"], f)
        d = read(mp) if mp else None
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
    ax.set_title(f"Trade-off per Module: Upgrades vs Test Pass Rate ({mode.upper()})", fontweight="bold")
    ax.legend(loc="lower left")
    save(fig, out, f"{mode}_pareto_upgrades_vs_passrate.png")


def g_versions_jumped_distribution(mods_by_flag, mode, out):
    parts = []
    for f, m in mods_by_flag.items():
        if m is not None and len(m) and METRIC_COL in m.columns:
            m = m[m["modules"] > 0]
            parts.append(pd.DataFrame({"flag": f, "v": m[METRIC_COL]}))
    if not parts:
        return
    d = pd.concat(parts).dropna(subset=["v"])
    if d.empty:
        return
    order = [f for f in FLAGS if f in set(d["flag"])]
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(data=d, x="flag", y="v", order=order, hue="flag", palette=COLORS, legend=False,
                showmeans=True, meanprops=dict(marker="o", markerfacecolor="white", markeredgecolor="black"),
                fliersize=0, ax=ax)
    sns.stripplot(data=d, x="flag", y="v", order=order, color="black", size=2.5, alpha=0.35, ax=ax)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f.capitalize() for f in order])
    ax.set_title(f"{METRIC_NAME} per Module ({mode.upper()}, symlog scale)", fontweight="bold")
    ax.set_xlabel("Update flag", fontweight="bold")
    ax.set_ylabel(METRIC_NAME, fontweight="bold")
    save(fig, out, f"{mode}_versions_jumped_distribution_box.png")


def g_jump_intensity_by_flag(tidy, mode, out):
    if METRIC_COL != "versions_jumped":
        return                                   # needs real version jumps (collector --lag)
    sub = tidy[tidy["built"]].groupby("flag")[["versions_jumped", "upgraded"]].sum().reset_index()
    if sub.empty:
        return
    sub["intensity"] = np.where(sub["upgraded"] > 0, sub["versions_jumped"] / sub["upgraded"], 0)

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(data=sub, x="flag", y="intensity", hue="flag", order=FLAGS, palette=COLORS, legend=False, ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.2f", padding=3, fontsize=9)
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Avg Versions Jumped per Upgraded Dependency", fontweight="bold")
    ax.set_title(f"Upgrade Intensity ({mode.upper()})", fontweight="bold", pad=15)
    save(fig, out, f"{mode}_jump_intensity_by_flag.png")


def g_upgrades_vs_jumps_comparison(tidy, mode, out):
    if METRIC_COL != "versions_jumped":
        return
    sub = tidy[tidy["built"]].groupby("flag")[["upgraded", "versions_jumped"]].sum().reset_index()
    if sub.empty:
        return
    sub["ratio"] = np.where(sub["upgraded"] > 0, sub["versions_jumped"] / sub["upgraded"], 0.0)

    sub["flag"] = pd.Categorical(sub["flag"], categories=FLAGS, ordered=True)
    sub = sub.sort_values("flag").reset_index(drop=True)

    fig, ax1 = plt.subplots(figsize=(10, 6))
    x = np.arange(len(sub))
    width = 0.26

    rects1 = ax1.bar(x - width, sub["upgraded"], width, label="Upgraded Dependencies Count", color="#4c72b0")
    rects2 = ax1.bar(x, sub["versions_jumped"], width, label="Total Versions Jumped", color="#dd8452")

    ax1.set_xlabel("Update Flag", fontweight="bold")
    ax1.set_ylabel("Cumulative Count (Upgraded & Jumped)", fontweight="bold", color="#333333")
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(f).capitalize() for f in sub["flag"]])

    ax2 = ax1.twinx()
    rects3 = ax2.bar(x + width, sub["ratio"], width, label="Jump Ratio (Jumped / Upgraded)", color="#55a868", alpha=0.9)
    ax2.set_ylabel("Ratio (Versions Jumped per Upgraded Dep)", fontweight="bold", color="#55a868")
    ax2.tick_params(axis="y", labelcolor="#55a868")
    ax2.grid(False)

    ax1.bar_label(rects1, fmt="%d", padding=3, fontsize=7)
    ax1.bar_label(rects2, fmt="%d", padding=3, fontsize=7)
    ax2.bar_label(rects3, fmt="%.2f", padding=3, fontsize=7)

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left", frameon=True)

    ax1.set_title(f"Volume, Magnitude, and Jump Intensity per Update Flag ({mode.upper()})", fontweight="bold", pad=15)
    save(fig, out, f"{mode}_volume_vs_magnitude_comparison.png")


def _has_lag(tidy, cols):
    return all(c in tidy.columns and tidy[c].notna().any() for c in cols)


def g_technical_lag_reduction(tidy, mode, out):
    if not _has_lag(tidy, ["lag_days_before", "lag_days_after"]):
        return
    sub = tidy[tidy["built"]].groupby("flag")[["lag_days_before", "lag_days_after"]].mean().reset_index()
    if sub.empty:
        return
    melted = sub.melt(id_vars="flag", value_vars=["lag_days_before", "lag_days_after"],
                      var_name="Phase", value_name="Avg Lag Days")
    melted["Phase"] = melted["Phase"].map({"lag_days_before": "Before Update", "lag_days_after": "After Update"})

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(data=melted, x="flag", y="Avg Lag Days", hue="Phase", order=FLAGS, palette="Set2", ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.1f", padding=3, fontsize=8)
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Average Technical Lag (Days)", fontweight="bold")
    ax.set_title(f"Technical Lag (Days) Before vs. After Upgrading ({mode.upper()})", fontweight="bold", pad=15)
    ax.legend(title="State", loc="upper right")
    save(fig, out, f"{mode}_technical_lag_days_comparison.png")


def g_stale_dependencies_breakdown(tidy, mode, out):
    cols = ["stale_major_before", "stale_minor_before", "stale_patch_before",
            "stale_major_after", "stale_minor_after", "stale_patch_after"]
    if not _has_lag(tidy, cols):
        return

    sub = tidy[tidy["built"]][["flag"] + cols].groupby("flag").sum().reset_index()
    if sub.empty:
        return

    rows = []
    for _, r in sub.iterrows():
        for phase in ("before", "after"):
            for kind in ("major", "minor", "patch"):
                rows.append({"flag": r["flag"], "Type": kind.capitalize(), "Phase": phase.capitalize(),
                             "Count": r[f"stale_{kind}_{phase}"]})
    df_stale = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.barplot(data=df_stale, x="flag", y="Count", hue="Type", order=FLAGS, palette="muted", ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%d", padding=2, fontsize=7)
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Total Stale Dependencies", fontweight="bold")
    ax.set_title(f"Stale Dependencies Breakdown ({mode.upper()})", fontweight="bold", pad=15)
    ax.legend(title="Stale Type", loc="upper right", bbox_to_anchor=(1.15, 1.0))
    save(fig, out, f"{mode}_stale_dependencies_breakdown.png")


def g_lag_days_reduction_repo(tidy, repos, mode, out):
    if not _has_lag(tidy, ["lag_days_reduction"]):
        return
    red = pivot(tidy, "lag_days_reduction", repos)
    built = pivot(tidy, "built", repos).fillna(False).astype(bool)
    y, h = np.arange(len(repos)), 0.26

    fig, ax = plt.subplots(figsize=(11, max(7, len(repos) * 0.5)))
    for i, flag in enumerate(FLAGS):
        vals = red[flag].fillna(0)
        bars = ax.barh(y + (i - 1) * h, vals, h, label=flag.capitalize(), color=COLORS[flag])
        ax.bar_label(bars, labels=[f"{int(v)}" if b else f"{int(v)} ✗" for v, b in zip(vals, built[flag])],
                     padding=3, fontsize=7)
    ax.set_yticks(y)
    ax.set_yticklabels(repos, fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlabel("Total Technical Lag Days Reduced (summed over modules)   ✗ = build failed", fontweight="bold")
    ax.set_title(f"Technical Lag Days Reduction by Repository and Flag ({mode.upper()})", fontweight="bold", pad=15)
    ax.legend(loc="lower right", frameon=True)
    save(fig, out, f"{mode}_repo_lag_days_reduction.png")


# ------------------------------------------------------------------------------ main

def main():
    global METRIC_COL, METRIC_NAME
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root")
    ap.add_argument("--mode", type=str, default="rq2", choices=["rq2", "base", "base_range"],
                    help="Analysis mode: rq2 or base (base_range is an alias)")
    ap.add_argument("--out", type=Path, default=None, help="Output directory for graphs")
    ap.add_argument("--exclude", nargs="*", default=[], help="repositories to exclude")
    ap.add_argument("--common-built-only", action="store_true",
                    help="Filter analysis to repositories that successfully built across ALL flags")
    a = ap.parse_args()
    mode = "base_range" if a.mode in ("base", "base_range") else "rq2"

    root = a.root.resolve()
    out = a.out or (root / "graphs" / mode)
    out.mkdir(parents=True, exist_ok=True)

    names = files_for(mode)
    print(f"Mode {mode}: reading results/{names['results']} (+ _repos.csv if present)")
    import hashlib
    for f in FLAGS:
        mine = root / "results" / names["results"].format(flag=f)
        other = root / "results" / files_for("rq2" if mode == "base_range" else "base_range")["results"].format(flag=f)
        if mine.exists() and other.exists():
            same = hashlib.md5(mine.read_bytes()).hexdigest() == hashlib.md5(other.read_bytes()).hexdigest()
            if same:
                print(f"[WARN] {mine.name} is byte-identical to {other.name}: the collector wrote the same data for "
                      f"both modes (check --mode / --log-dir of the collector run).", file=sys.stderr)

    frames, mods_by_flag = [], {}
    for f in FLAGS:
        df, mods = load_flag(root, mode, f)
        if not df.empty:
            frames.append(df)
        mods_by_flag[f] = mods

    if not frames:
        print(f"No result CSVs found for mode '{mode}'. Have you run collect_results.py --mode {mode}?")
        return

    tidy = pd.concat(frames, ignore_index=True)
    tidy = tidy[~tidy["repo"].isin(a.exclude)]
    mods_by_flag = {f: (m[~m["repo"].isin(a.exclude)] if m is not None else None) for f, m in mods_by_flag.items()}

    base = load_baseline(root)
    if base is not None:
        tidy = tidy.merge(base, on="repo", how="left")
        tidy["rq1_built"] = tidy["rq1_built"].fillna(False).astype(bool)
        if "pass_rate" in tidy.columns and "rq1_pass_rate" in tidy.columns:
            tidy["pass_delta"] = tidy["pass_rate"] - tidy["rq1_pass_rate"]

    # test numbers of failed builds are not comparable
    for c in ("pass_rate", "pass_delta"):
        if c in tidy.columns:
            tidy.loc[~tidy["built"].astype(bool), c] = np.nan

    # version jumps need the collector's --lag; otherwise fall back to the plain upgraded count
    if tidy["versions_jumped"].fillna(0).sum() > 0:
        METRIC_COL, METRIC_NAME = "versions_jumped", "Versions jumped"
    else:
        METRIC_COL, METRIC_NAME = "upgraded", "Upgraded dependencies"
        print("[WARN] versions_jumped is empty/zero in every CSV (collector run without --lag?); "
              "the jump graphs use the upgraded-dependency count instead and the jump-intensity graphs are skipped.",
              file=sys.stderr)

    built_repos = {f: set(tidy[(tidy["flag"] == f) & tidy["built"].astype(bool)]["repo"]) for f in FLAGS}
    common_repos = set.intersection(*built_repos.values()) if built_repos else set()

    print(f"\n[SURVIVORSHIP BIAS AUDIT ({mode.upper()})]")
    for f in FLAGS:
        n = int((tidy["flag"] == f).sum())
        print(f"  - Built successfully ({f}): {len(built_repos[f])} of {n} repositories")
    print(f"  - Built successfully across ALL flags (common intersection): {len(common_repos)} repositories\n")

    if a.common_built_only:
        print(f"[INFO] Filtering dataset to the {len(common_repos)} common successfully built repositories (--common-built-only enabled).")
        tidy = tidy[tidy["repo"].isin(common_repos)]
        mods_by_flag = {f: (m[m["repo"].isin(common_repos)] if m is not None else None) for f, m in mods_by_flag.items()}
        built_repos = {f: set(tidy[(tidy["flag"] == f) & tidy["built"].astype(bool)]["repo"]) for f in FLAGS}

    mods_built = {f: (m[m["repo"].isin(built_repos[f])] if m is not None else None)
                  for f, m in mods_by_flag.items()}

    diagnostics(root, mods_by_flag)
    repos = sorted(tidy["repo"].unique())
    if not repos:
        print("No data found; have the pipelines been run?")
        return

    table = root / "results" / f"{mode}_repo_flag_table.csv"
    tidy.sort_values(["repo", "flag"]).to_csv(table, index=False)
    print(f"{len(repos)} repositories; table written to {table}")

    g_upgrades_by_repo(tidy, repos, mode, out)
    g_upgrade_pct_heatmap(tidy, repos, mode, out)
    g_action_averages(mods_built, mode, out)
    g_test_success_by_repo(tidy, repos, mode, out)
    g_test_strip(tidy, repos, mode, out)
    g_macro(tidy, mode, out)
    g_upgrades_vs_tests(tidy, mode, out)
    g_delta_heatmap(tidy, repos, mode, out)
    g_pareto(root, mode, out, built_repos)
    g_versions_jumped_distribution(mods_built, mode, out)
    g_jump_intensity_by_flag(tidy, mode, out)
    g_upgrades_vs_jumps_comparison(tidy, mode, out)
    g_technical_lag_reduction(tidy, mode, out)
    g_stale_dependencies_breakdown(tidy, mode, out)
    g_lag_days_reduction_repo(tidy, repos, mode, out)
    print(f"All graphs successfully written to {out}")


if __name__ == "__main__":
    main()