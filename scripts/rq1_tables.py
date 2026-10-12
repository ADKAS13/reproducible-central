import os
import numpy as np
import pandas as pd

# -------------------------------------------------------------------
# Paths Setup
# -------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join("results")
TABLES_DIR = os.path.join(SCRIPT_DIR, "tables")
os.makedirs(TABLES_DIR, exist_ok=True)

rq1_repo_file = os.path.join(RESULTS_DIR, "rq1_results.csv")
base_repo_file = os.path.join(RESULTS_DIR, "base_results.csv")

if not os.path.exists(base_repo_file):
    raise FileNotFoundError(f"Missing required baseline file: {base_repo_file}")

df_base = pd.read_csv(base_repo_file)
df_rq1 = pd.read_csv(rq1_repo_file) if os.path.exists(rq1_repo_file) else pd.DataFrame(columns=df_base.columns)

# -------------------------------------------------------------------
# Data Normalization & Master Alignment (Baseline as Backbone)
# -------------------------------------------------------------------
df_base["build_success_num"] = df_base["build_success"].astype(int)
df_base["pass_rate"] = pd.to_numeric(
    df_base["pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
).fillna(0.0)

# Normalize RQ1 Data
df_rq1["build_success_num"] = df_rq1["build_success"].astype(int) if "build_success" in df_rq1.columns else 0
df_rq1["pass_rate"] = pd.to_numeric(
    df_rq1["pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
).fillna(0.0)

if "equivalence_rate" in df_rq1.columns:
    df_rq1["equivalence_rate"] = pd.to_numeric(
        df_rq1["equivalence_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
    ).fillna(0.0)
else:
    df_rq1["equivalence_rate"] = 0.0

# Merge datasets on 'repo' using baseline as master list
df_base = df_base.sort_values(by="repo").reset_index(drop=True)
df_merged = pd.merge(df_base, df_rq1, on="repo", how="left", suffixes=("_base", "_rq1"))

# Safe column mapping post-merge
df_merged["build_success_num_rq1"] = df_merged.get("build_success_num_rq1", df_merged.get("build_success_num", 0)).fillna(0).astype(int)
df_merged["total_tests_rq1"] = df_merged["total_tests_base"]
df_merged["total_passed_rq1"] = df_merged.get("total_passed_rq1", df_merged.get("total_passed", 0)).fillna(0)

df_merged["pass_rate_rq1"] = np.where(
    df_merged["total_tests_rq1"] > 0,
    (df_merged["total_passed_rq1"] / df_merged["total_tests_rq1"]) * 100,
    0.0
)

equiv_col = "equivalence_rate_rq1" if "equivalence_rate_rq1" in df_merged.columns else ("equivalence_rate" if "equivalence_rate" in df_merged.columns else None)
df_merged["equivalence_rate_rq1"] = df_merged[equiv_col].fillna(0.0) if equiv_col else 0.0

# -------------------------------------------------------------------
# Table 1: Per-Repository Breakdown (Base vs. RQ1 Side-by-Side)
# -------------------------------------------------------------------
latex_repo_table = """\\begin{table}[htbp]
\\centering
\\caption{Per-Repository Comparison: Build Success, Test Pass Rate, and Module Equivalence (Base vs. RQ1)}
\\label{tab:rq1_repo_breakdown}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lcccc}
\\toprule
\\textbf{Repository} & \\textbf{Modules} & \\textbf{Build (Base / RQ1)} & \\textbf{Test Pass (Base / RQ1)} & \\textbf{Equivalence (RQ1)} \\\\
\\midrule
"""

for _, row in df_merged.iterrows():
    repo_name = row["repo"]
    
    # 1. Build Success
    base_b_mark = "\\cmark" if int(row.get("build_success_num_base", 0)) == 1 else "\\xmark"
    rq1_b_mark = "\\cmark" if int(row.get("build_success_num_rq1", 0)) == 1 else "\\xmark"
    build_cell = f"{base_b_mark} / {rq1_b_mark}"
    
    # 2. Test Pass Rate
    base_pass = row.get("pass_rate_base", 0.0)
    rq1_pass = row.get("pass_rate_rq1", 0.0)
    
    base_pass_str = f"{base_pass:.1f}\\%" if pd.notnull(base_pass) else "?"
    rq1_pass_str = f"{rq1_pass:.1f}\\%" if pd.notnull(row.get("total_passed_rq1")) else "?"
    pass_cell = f"{base_pass_str} / {rq1_pass_str}"
    
    # 3. Equivalence Rate
    rq1_equiv = row.get("equivalence_rate_rq1", 0.0)
    equiv_cell = f"{rq1_equiv:.1f}\\%" if rq1_equiv > 0 else "N/A"

    latex_repo_table += (
        f"{repo_name} & "
        f"{int(row.get('total_modules_base', row.get('total_modules', 0)))} & "
        f"{build_cell} & "
        f"{pass_cell} & "
        f"{equiv_cell} \\\\\n"
    )

latex_repo_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

with open(os.path.join(TABLES_DIR, "rq1_per_repo_breakdown.tex"), "w") as f:
    f.write(latex_repo_table)

print("Saved: rq1_per_repo_breakdown.tex")

# -------------------------------------------------------------------
# Table 2: Macro Summary (Baseline All vs. RQ1 All vs. Baseline Passing vs. RQ1 Passing)
# -------------------------------------------------------------------
total_repos = len(df_merged)

# 1. Baseline Stats (All Repositories, N=27)
base_build_rate = df_merged["build_success_num_base"].mean() * 100
base_pass_mean = df_merged["pass_rate_base"].mean()
base_pass_std = df_merged["pass_rate_base"].std()
base_total_tests = df_merged["total_tests_base"].sum()
base_build_count = f"{int(df_merged['build_success_num_base'].sum())}/{total_repos}"

# 2. RQ1 Stats (All Repositories, N=27)
rq1_all_build_rate = df_merged["build_success_num_rq1"].mean() * 100
rq1_all_pass_mean = df_merged["pass_rate_rq1"].mean()
rq1_all_pass_std = df_merged["pass_rate_rq1"].std()
rq1_all_total_tests = df_merged["total_tests_rq1"].sum()
rq1_all_build_count = f"{int(df_merged['build_success_num_rq1'].sum())}/{total_repos}"
rq1_all_equiv_mean = df_merged["equivalence_rate_rq1"].mean()

# 3. Passing Subset (N = passing_count, e.g., 24)
df_rq1_passing = df_merged[df_merged["build_success_num_rq1"] == 1]
passing_count = len(df_rq1_passing)

# Baseline Passing Stats (over the same 24 passing repos)
base_passing_build_rate = 100.0
base_passing_pass_mean = df_rq1_passing["pass_rate_base"].mean() if passing_count > 0 else 0.0
base_passing_pass_std = df_rq1_passing["pass_rate_base"].std() if passing_count > 0 else 0.0
base_passing_total_tests = df_rq1_passing["total_tests_base"].sum() if passing_count > 0 else 0
base_passing_build_count = f"{passing_count}/{passing_count}"

# RQ1 Passing Stats (over the 24 passing repos)
rq1_pass_mean = df_rq1_passing["pass_rate_rq1"].mean() if passing_count > 0 else 0.0
rq1_pass_std = df_rq1_passing["pass_rate_rq1"].std() if passing_count > 0 else 0.0
rq1_pass_total_tests = df_rq1_passing["total_tests_rq1"].sum() if passing_count > 0 else 0
rq1_pass_equiv_mean = df_rq1_passing["equivalence_rate_rq1"].mean() if passing_count > 0 else 0.0

latex_summary_table = f"""\\begin{{table}}[htbp]
\\centering
\\caption{{Macro Summary and Descriptive Statistics: Baseline vs. RQ1 ($N = {total_repos}$ Repositories)}}
\\label{{tab:rq1_macro_summary}}
\\resizebox{{\\linewidth}}{{!}}{{%
\\begin{{tabular}}{{lcccc}}
\\toprule
\\textbf{{Metric}} & \\textbf{{Baseline (All)}} & \\textbf{{RQ1 (All)}} & \\textbf{{Baseline (Passing)}} & \\textbf{{RQ1 (Passing)}} \\\\
\\midrule
Build Success Rate & {base_build_rate:.1f}\\% ({base_build_count}) & {rq1_all_build_rate:.1f}\\% ({rq1_all_build_count}) & {base_passing_build_rate:.1f}\\% ({base_passing_build_count}) & 100.0\\% ({passing_count}/{passing_count}) \\\\
Test Pass Rate (Mean $\\pm$ Std) & {base_pass_mean:.1f}\\% $\\pm$ {base_pass_std:.1f} & {rq1_all_pass_mean:.1f}\\% $\\pm$ {rq1_all_pass_std:.1f} & {base_passing_pass_mean:.1f}\\% $\\pm$ {base_passing_pass_std:.1f} & {rq1_pass_mean:.1f}\\% $\\pm$ {rq1_pass_std:.1f} \\\\
Module Equivalence Rate (Mean) & -- & {rq1_all_equiv_mean:.1f}\\% & -- & {rq1_pass_equiv_mean:.1f}\\% \\\\
Total Evaluated Tests & {base_total_tests:,} tests & {rq1_all_total_tests:,} tests & {base_passing_total_tests:,} tests & {rq1_pass_total_tests:,} tests \\\\
\\bottomrule
\\end{{tabular}}%
}}
\\end{{table}}"""

with open(os.path.join(TABLES_DIR, "rq1_macro_summary.tex"), "w") as f:
    f.write(latex_summary_table)

print("Saved: rq1_macro_summary.tex (4-Column Macro Summary Included)")