#!/usr/bin/env python3
"""
tables_rq2.py — LaTeX tables for RQ2 and Base Range (combined & per-mode).

Loads per-mode repo/flag tables (e.g. results/rq2_repo_flag_table.csv and
results/base_range_repo_flag_table.csv) when present, or builds them from
results/{prefix}_results_{flag}.csv, repos CSVs, and rq1_style_stats_*.csv.

Definitions:
- Failed builds are excluded from every statistic except build success rate.
- Test pass rate: mean over built repos of the per-repo rate (std is over the same repos).
- Per-module means: mean over built repos of count / modules; repos without modules
  are skipped for per-module ratios.
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FLAGS = ["major", "minor", "patch"]
ACTIONS = ["upgraded", "pinned", "downgraded", "added", "removed", "scope_changed"]
STALE_COLS = ["stale_major", "stale_minor", "stale_patch"]
LAG_CANDIDATES = STALE_COLS + ["lag_days_before", "lag_days_after", "versions_jumped"]
FLAVOR_RE = re.compile(r"^(RQ\d.*|base(?:_?range)?)$", re.IGNORECASE)


def mode_prefix(mode: str) -> str:
    return "base_range" if mode in ("base_range", "base") else "rq2"


def read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    if path is not None and path.exists():
        return pd.read_csv(path)
    return None


def drop_flavor_named(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "repo" not in df.columns:
        return df
    return df[~df["repo"].astype(str).str.match(FLAVOR_RE)].copy()


def as_bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "success", "passed"})


def find_stats_file(res_dir: Path, prefix: str, flag: str) -> Path | None:
    candidates = [
        res_dir / f"rq1_style_stats_{prefix}_{flag}.csv",
        res_dir / f"rq1_style_stats_{flag}.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


def find_repos_file(res_dir: Path, prefix: str, flag: str) -> Path | None:
    candidates = [
        res_dir / f"{prefix}_results_{flag}_repos.csv",
        res_dir / f"{prefix}_repos_{flag}.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


def build_mode_from_raw(res_dir: Path, mode: str) -> pd.DataFrame:
    prefix = mode_prefix(mode)
    frames = []

    for flag in FLAGS:
        mods_path = res_dir / f"{prefix}_results_{flag}.csv"
        mods = read_csv_if_exists(mods_path)
        if mods is None:
            continue
        mods = drop_flavor_named(mods)
        if mods.empty or "repo" not in mods.columns:
            continue

        for col in ACTIONS + ["total_before", "total_after", "build_time_s"]:
            if col in mods.columns:
                mods[col] = pd.to_numeric(mods[col], errors="coerce").fillna(0.0)
            else:
                mods[col] = 0.0

        present_lag = [c for c in LAG_CANDIDATES if c in mods.columns]
        for col in present_lag:
            mods[col] = pd.to_numeric(mods[col], errors="coerce")

        mods["built"] = as_bool_series(mods["build_success"]) if "build_success" in mods.columns else True

        if "module" in mods.columns:
            placeholder = mods["module"].astype(str) == "<no-report>"
        else:
            placeholder = pd.Series(False, index=mods.index)
        mods["modules"] = (~placeholder).astype(int)

        agg = {
            "built": "max",
            "build_time_s": "mean",
            "modules": "sum",
        }
        for c in ACTIONS + ["total_before", "total_after"]:
            agg[c] = "sum"
        for c in present_lag:
            agg[c] = "sum"

        df = mods.groupby("repo", as_index=False).agg(agg)
        df["flag"] = flag

        repos_path = find_repos_file(res_dir, prefix, flag)
        rtab = drop_flavor_named(read_csv_if_exists(repos_path))
        if rtab is not None and {"repo", "build_success"} <= set(rtab.columns):
            rb = (
                rtab.assign(built_repos=as_bool_series(rtab["build_success"]))[["repo", "built_repos"]]
                .drop_duplicates("repo")
            )
            df = df.merge(rb, on="repo", how="outer")
            df["flag"] = flag
            df["built"] = df["built_repos"].where(df["built_repos"].notna(), df["built"]).fillna(False).astype(bool)
            for c in ["modules"] + ACTIONS + ["total_before", "total_after"]:
                df[c] = df[c].fillna(0)
            df = df.drop(columns="built_repos")

        stats_path = find_stats_file(res_dir, prefix, flag)
        tests = drop_flavor_named(read_csv_if_exists(stats_path))
        if tests is not None and {"repo", "total_passed", "total_tests"} <= set(tests.columns):
            passed = pd.to_numeric(tests["total_passed"], errors="coerce")
            den = pd.to_numeric(tests["total_tests"], errors="coerce")
            if "total_skipped" in tests.columns:
                den = den - pd.to_numeric(tests["total_skipped"], errors="coerce").fillna(0)
            rate = np.where(den > 0, passed / den * 100.0, np.nan)
            repo_rates = (
                pd.DataFrame({"repo": tests["repo"], "pass_rate": rate})
                .groupby("repo", as_index=False)["pass_rate"]
                .mean()
            )
            df = df.merge(repo_rates, on="repo", how="left")

        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["mode"] = prefix
    return out


def load_mode_data(res_dir: Path, mode: str) -> pd.DataFrame:
    prefix = mode_prefix(mode)
    table_candidates = [
        res_dir / f"{prefix}_repo_flag_table.csv",
        res_dir / f"{mode}_repo_flag_table.csv",
    ]
    if prefix == "rq2":
        table_candidates.append(res_dir / "rq2_repo_flag_table.csv")

    tpath = next((p for p in table_candidates if p.exists()), None)
    df = drop_flavor_named(read_csv_if_exists(tpath)) if tpath is not None else None

    if df is None or df.empty:
        df = build_mode_from_raw(res_dir, prefix)
        if df.empty:
            return pd.DataFrame()

    df["mode"] = prefix
    df["built"] = as_bool_series(df["built"]) if "built" in df.columns else False

    for c in ACTIONS + ["modules", "total_before", "total_after"]:
        if c not in df.columns:
            df[c] = np.nan
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in LAG_CANDIDATES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    if "pass_rate" not in df.columns:
        df["pass_rate"] = np.nan
    else:
        df["pass_rate"] = pd.to_numeric(df["pass_rate"], errors="coerce")

    # Also try loading RQ1 baseline pass rates if present
    rq1_stats = res_dir / "rq1_style_stats.csv"
    if "rq1_pass_rate" not in df.columns and rq1_stats.exists():
        rq1 = drop_flavor_named(pd.read_csv(rq1_stats))
        if {"repo", "total_passed", "total_tests"} <= set(rq1.columns):
            p = pd.to_numeric(rq1["total_passed"], errors="coerce")
            d = pd.to_numeric(rq1["total_tests"], errors="coerce")
            if "total_skipped" in rq1.columns:
                d = d - pd.to_numeric(rq1["total_skipped"], errors="coerce").fillna(0)
            rq1_df = (
                pd.DataFrame({"repo": rq1["repo"], "rq1_pass_rate": np.where(d > 0, p / d * 100.0, np.nan)})
                .groupby("repo", as_index=False)["rq1_pass_rate"]
                .mean()
            )
            df = df.merge(rq1_df, on="repo", how="left")

    if "rq1_pass_rate" not in df.columns:
        df["rq1_pass_rate"] = np.nan
    if "rq1_built" not in df.columns:
        df["rq1_built"] = df["rq1_pass_rate"].notna()

    # Reindex to full (repo, flag) grid per mode
    repos = sorted(df["repo"].dropna().unique())
    full = pd.MultiIndex.from_product([repos, FLAGS], names=["repo", "flag"])
    indexed = df.set_index(["repo", "flag"]).reindex(full).reset_index()
    indexed["mode"] = prefix
    indexed["built"] = indexed["built"].fillna(False).astype(bool)

    rq1_map = df.groupby("repo")["rq1_pass_rate"].first()
    rq1_ok_map = df.groupby("repo")["rq1_built"].first().fillna(False).astype(bool)
    indexed["rq1_pass_rate"] = indexed["repo"].map(rq1_map)
    indexed["rq1_built"] = indexed["repo"].map(rq1_ok_map).fillna(False).astype(bool)

    eligible = indexed["built"] & indexed["modules"].notna() & (indexed["modules"] > 0)
    for c in ACTIONS:
        indexed[f"{c}_pm"] = np.where(eligible, indexed[c] / indexed["modules"], np.nan)

    return indexed


def fmt_cnt(v) -> str:
    return "--" if pd.isna(v) else f"{int(round(v)):,}"


def fmt_num(v, spec=".1f", suffix="") -> str:
    return "--" if pd.isna(v) else f"{v:{spec}}{suffix}"


def write_macro_table(df: pd.DataFrame, out_path: Path, label_prefix: str) -> None:
    modes = list(dict.fromkeys(df["mode"].dropna()))
    multi_mode = len(modes) > 1

    if not multi_mode:
        m = modes[0]
        sub = df[df["mode"] == m]
        cols = []
        for f in FLAGS:
            tf = sub[sub["flag"] == f]
            ok = tf[tf["built"]]
            mod_sum = ok["modules"].sum()
            upg_per_mod = ok["upgraded"].sum() / mod_sum if mod_sum > 0 else np.nan
            cols.append({
                "build": fmt_num(tf["built"].mean() * 100.0, ".1f", "\\%"),
                "tests": fmt_num(ok["pass_rate"].mean(), ".1f", "\\%") + " $\\pm$ " + fmt_num(ok["pass_rate"].std(), ".1f"),
                "upg_total": fmt_cnt(ok["upgraded"].sum()),
                "upg_pm": fmt_num(upg_per_mod, ".2f"),
            })

        tex = "\n".join([
            r"\begin{table}[htbp]",
            r"\centering",
            rf"\caption{{Macro Summary Across Update Flags ({m.upper()}). Failed builds excluded except build rate.}}",
            rf"\label{{tab:{label_prefix}_macro_summary}}",
            r"\begin{tabular}{lccc}",
            r"\toprule",
            r"\textbf{Metric} & \textbf{Major} & \textbf{Minor} & \textbf{Patch} \\",
            r"\midrule",
            "Build Success Rate & " + " & ".join(c["build"] for c in cols) + r" \\",
            r"Test Pass Rate (Mean $\pm$ Std) & " + " & ".join(c["tests"] for c in cols) + r" \\",
            "Upgraded Dependencies (Total) & " + " & ".join(c["upg_total"] for c in cols) + r" \\",
            "Upgraded Dependencies (Per Module) & " + " & ".join(c["upg_pm"] for c in cols) + r" \\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ])
    else:
        headers = ["\\textbf{Metric}"] + [f"\\textbf{{{f.capitalize()} (RQ2 / Base)}}" for f in FLAGS]
        rows_data = {
            "Build Success Rate": [],
            r"Test Pass Rate (Mean $\pm$ Std)": [],
            "Upgraded Dependencies (Total)": [],
            "Upgraded / Module (Built)": [],
        }
        for f in FLAGS:
            parts = {"build": [], "tests": [], "upg": [], "upm": []}
            for m in ("rq2", "base_range"):
                sub = df[(df["mode"] == m) & (df["flag"] == f)]
                if sub.empty:
                    parts["build"].append("--")
                    parts["tests"].append("--")
                    parts["upg"].append("--")
                    parts["upm"].append("--")
                    continue
                ok = sub[sub["built"]]
                mod_sum = ok["modules"].sum()
                upm = ok["upgraded"].sum() / mod_sum if mod_sum > 0 else np.nan
                parts["build"].append(fmt_num(sub["built"].mean() * 100.0, ".1f", "\\%"))
                mean_str = fmt_num(ok["pass_rate"].mean(), ".1f", "\\%")
                std_str = fmt_num(ok["pass_rate"].std(), ".1f")
                parts["tests"].append(f"{mean_str}$\\pm${std_str}")
                parts["upg"].append(fmt_cnt(ok["upgraded"].sum()))
                parts["upm"].append(fmt_num(upm, ".2f"))

            rows_data["Build Success Rate"].append(" / ".join(parts["build"]))
            rows_data[r"Test Pass Rate (Mean $\pm$ Std)"].append(" / ".join(parts["tests"]))
            rows_data["Upgraded Dependencies (Total)"].append(" / ".join(parts["upg"]))
            rows_data["Upgraded / Module (Built)"].append(" / ".join(parts["upm"]))

        tex = "\n".join([
            r"\begin{table}[htbp]",
            r"\centering",
            r"\caption{Combined Macro Summary: RQ2 vs. Base Range Across Update Flags (built repositories).}",
            rf"\label{{tab:{label_prefix}_combined_macro}}",
            r"\resizebox{\linewidth}{!}{%",
            r"\begin{tabular}{lccc}",
            r"\toprule",
            " & ".join(headers) + r" \\",
            r"\midrule",
            *[f"{k} & " + " & ".join(v) + r" \\" for k, v in rows_data.items()],
            r"\bottomrule",
            r"\end{tabular}%",
            r"}",
            r"\end{table}",
        ])

    out_path.write_text(tex + "\n")
    print(f"Saved: {out_path.name}")


def write_action_comparison_table(df: pd.DataFrame, out_path: Path, label_prefix: str) -> None:
    built_mods = df[df["built"] & df["modules"].notna() & (df["modules"] > 0)].copy()
    if built_mods.empty:
        return

    present_actions = [a for a in ACTIONS if a in built_mods.columns]
    if not present_actions:
        return

    # Compute per-module mean across built repos per (mode, flag)
    for a in present_actions:
        built_mods[f"{a}_ratio"] = built_mods[a] / built_mods["modules"]

    active_actions = [
        a for a in present_actions
        if built_mods[f"{a}_ratio"].fillna(0.0).abs().max() > 1e-9
    ]
    omitted_actions = [a for a in present_actions if a not in active_actions]
    if not active_actions:
        active_actions = present_actions
        omitted_actions = []

    omitted_note = ""
    if omitted_actions:
        pretty_omitted = ", ".join(a.replace("_", " ") for a in omitted_actions)
        omitted_note = f" Omitted actions with zero mean across all flags and modes: {pretty_omitted}."

    modes = [m for m in ("rq2", "base_range") if m in set(df["mode"].dropna())]
    if not modes:
        modes = list(dict.fromkeys(df["mode"].dropna()))

    col_headers = ["\\textbf{Action}", "\\textbf{Mode}"] + [f"\\textbf{{{f.capitalize()}}}" for f in FLAGS]
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\caption{{Average Dependency Changes per Module (Built Repositories).{omitted_note}}}",
        rf"\label{{tab:{label_prefix}_action_averages}}",
        r"\begin{tabular}{ll" + "r" * len(FLAGS) + "}",
        r"\toprule",
        " & ".join(col_headers) + r" \\",
        r"\midrule",
    ]

    for idx_a, action in enumerate(active_actions):
        if idx_a > 0:
            lines.append(r"\midrule")
        label_a = action.replace("_", " ").capitalize()
        for idx_m, m in enumerate(modes):
            mode_label = "RQ2" if m == "rq2" else "Base range"
            vals = []
            for f in FLAGS:
                sub = built_mods[(built_mods["mode"] == m) & (built_mods["flag"] == f)]
                vals.append(fmt_num(sub[f"{action}_ratio"].mean(), ".2f"))
            first_col = label_a if idx_m == 0 else ""
            lines.append(f"{first_col} & {mode_label} & " + " & ".join(vals) + r" \\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {out_path.name}")


def write_stale_table(df: pd.DataFrame, out_path: Path, label_prefix: str) -> None:
    available_stale = [c for c in STALE_COLS if c in df.columns and df[c].notna().any()]
    if not available_stale:
        return

    modes = [m for m in ("rq2", "base_range") if m in set(df["mode"].dropna())]
    if not modes:
        modes = list(dict.fromkeys(df["mode"].dropna()))

    col_headers = ["\\textbf{Staleness Tier}", "\\textbf{Mode}"] + [f"\\textbf{{{f.capitalize()}}}" for f in FLAGS]
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Stale Dependency Counts Across Update Flags (Built Repositories).}",
        rf"\label{{tab:{label_prefix}_stale_dependencies}}",
        r"\begin{tabular}{ll" + "r" * len(FLAGS) + "}",
        r"\toprule",
        " & ".join(col_headers) + r" \\",
        r"\midrule",
    ]

    for idx_s, col in enumerate(available_stale):
        if idx_s > 0:
            lines.append(r"\midrule")
        tier_label = col.replace("_", " ").capitalize()
        for idx_m, m in enumerate(modes):
            mode_label = "RQ2" if m == "rq2" else "Base range"
            vals = []
            for f in FLAGS:
                sub = df[(df["mode"] == m) & (df["flag"] == f) & df["built"]]
                vals.append(fmt_cnt(sub[col].sum()))
            first_col = tier_label if idx_m == 0 else ""
            lines.append(f"{first_col} & {mode_label} & " + " & ".join(vals) + r" \\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {out_path.name}")


def write_repo_breakdown_table(df: pd.DataFrame, out_path: Path, label_prefix: str) -> None:
    modes = [m for m in ("rq2", "base_range") if m in set(df["mode"].dropna())]
    if not modes:
        modes = list(dict.fromkeys(df["mode"].dropna()))

    multi_mode = len(modes) > 1
    repos = sorted(df["repo"].dropna().unique())
    if not repos:
        return

    if not multi_mode:
        m = modes[0]
        sub = df[df["mode"] == m].set_index(["repo", "flag"])
        head = (
            r"\textbf{Repository} & \textbf{Flag} & \textbf{Upgraded} & "
            r"\textbf{Pinned} & \textbf{Downgraded} & \textbf{Build} \\"
        )
        lines = [
            r"\onecolumn",
            r"\begin{small}",
            r"\setlength{\tabcolsep}{4pt}",
            r"\begin{longtable}{llrrrr}",
            rf"\caption{{Per-Repository Dependency Actions and Build Status ({m.upper()}).}}",
            rf"\label{{tab:{label_prefix}_repo_breakdown}} \\",
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
        ]
        for n, repo in enumerate(repos):
            if n:
                lines.append(r"\midrule")
            for i, flag in enumerate(FLAGS):
                r = sub.loc[(repo, flag)]
                ok = bool(r["built"])
                name = repo if i == 0 else ""
                mark = r"\cmark" if ok else r"\xmark"
                lines.append(
                    f"{name} & {flag.capitalize()} & {fmt_cnt(r['upgraded'])} & "
                    f"{fmt_cnt(r['pinned'])} & {fmt_cnt(r['downgraded'])} & {mark} \\\\"
                )
        lines.extend([r"\end{longtable}", r"\end{small}", r"\twocolumn"])
    else:
        sub = df.set_index(["mode", "repo", "flag"])
        head = (
            r"\textbf{Repository} & \textbf{Flag} & \textbf{RQ2 Upg / Build} & "
            r"\textbf{Base Upg / Build} \\"
        )
        lines = [
            r"\onecolumn",
            r"\begin{small}",
            r"\setlength{\tabcolsep}{4pt}",
            r"\begin{longtable}{llcc}",
            r"\caption{Per-Repository Upgraded Counts and Build Status: RQ2 vs. Base Range.}",
            rf"\label{{tab:{label_prefix}_combined_repo_breakdown}} \\",
            r"\toprule", head, r"\midrule", r"\endfirsthead",
            "",
            r"\multicolumn{4}{c}{{\tablename\ \thetable\ -- continued from previous page}} \\",
            r"\toprule", head, r"\midrule", r"\endhead",
            "",
            r"\midrule",
            r"\multicolumn{4}{r}{{Continued on next page}} \\",
            r"\endfoot",
            "",
            r"\bottomrule",
            r"\endlastfoot",
        ]
        for n, repo in enumerate(repos):
            if n:
                lines.append(r"\midrule")
            for i, flag in enumerate(FLAGS):
                name = repo if i == 0 else ""
                cells = []
                for m in ("rq2", "base_range"):
                    if (m, repo, flag) in sub.index:
                        row = sub.loc[(m, repo, flag)]
                        mark = r"\cmark" if bool(row["built"]) else r"\xmark"
                        cells.append(f"{fmt_cnt(row['upgraded'])} ({mark})")
                    else:
                        cells.append("--")
                lines.append(f"{name} & {flag.capitalize()} & " + " & ".join(cells) + r" \\")
        lines.extend([r"\end{longtable}", r"\end{small}", r"\twocolumn"])

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {out_path.name}")


def write_test_table(df: pd.DataFrame, out_path: Path, label_prefix: str) -> None:
    repos = sorted(df["repo"].dropna().unique())
    if not repos:
        return

    def pass_cell(v, built):
        if not built:
            return r"\xmark"
        return "n/a" if pd.isna(v) else f"{v:.1f}\\%"

    sub = df.set_index(["mode", "repo", "flag"])
    primary_mode = "rq2" if "rq2" in set(df["mode"].dropna()) else df["mode"].iloc[0]

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Test Success Rate (\%) by Repository Across Update Flags (\xmark{} = build failed, excluded).}",
        rf"\label{{tab:{label_prefix}_test_success_rates}}",
        r"\resizebox{\linewidth}{!}{%",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"\textbf{Repository} & \textbf{RQ1 (\%)} & \textbf{Major (\%)} & \textbf{Minor (\%)} & \textbf{Patch (\%)} \\",
        r"\midrule",
    ]

    for repo in repos:
        m_rows = df[(df["mode"] == primary_mode) & (df["repo"] == repo)]
        rq1_val = m_rows["rq1_pass_rate"].iloc[0] if not m_rows.empty else np.nan
        rq1_ok = bool(m_rows["rq1_built"].iloc[0]) if not m_rows.empty else False
        cols = [pass_cell(rq1_val, rq1_ok)]
        for f in FLAGS:
            if (primary_mode, repo, f) in sub.index:
                r = sub.loc[(primary_mode, repo, f)]
                cols.append(pass_cell(r["pass_rate"], bool(r["built"])))
            else:
                cols.append(r"\xmark")
        lines.append(f"{repo} & " + " & ".join(cols) + r" \\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\end{table}",
    ])
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {out_path.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root (default: cwd)")
    ap.add_argument("--mode", choices=["rq2", "base_range", "both"], default="both",
                    help="Which mode(s) to tabulate (default: both)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "tables",
                    help="Output directory for .tex files")
    args = ap.parse_args()

    res_dir = args.root.resolve() / "results"
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if not res_dir.exists():
        sys.exit(f"Results directory not found: {res_dir}")

    target_modes = ["rq2", "base_range"] if args.mode == "both" else [args.mode]
    loaded = {}
    for m in target_modes:
        mdf = load_mode_data(res_dir, m)
        if not mdf.empty:
            loaded[m] = mdf
            write_macro_table(mdf, out_dir / f"{m}_per_flag_summary.tex", m)
            write_repo_breakdown_table(mdf, out_dir / f"{m}_per_repo_breakdown.tex", m)
            write_test_table(mdf, out_dir / f"{m}_test_success_rates.tex", m)
            write_stale_table(mdf, out_dir / f"{m}_stale_dependencies.tex", m)

    if not loaded:
        sys.exit(f"No result tables or raw CSVs found in {res_dir}")

    combined = pd.concat(list(loaded.values()), ignore_index=True)
    if len(loaded) > 1:
        write_macro_table(combined, out_dir / "combined_macro_summary.tex", "combined")
        write_repo_breakdown_table(combined, out_dir / "combined_per_repo_breakdown.tex", "combined")
        write_stale_table(combined, out_dir / "combined_stale_dependencies.tex", "combined")

    write_action_comparison_table(combined, out_dir / "combined_flag_action_comparison.tex", "combined")


if __name__ == "__main__":
    main()