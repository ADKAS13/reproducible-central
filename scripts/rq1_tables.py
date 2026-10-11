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

# File paths for RQ1
rq1_repo_file = os.path.join(RESULTS_DIR, "rq1_results.csv")
rq1_module_file = os.path.join(RESULTS_DIR, "rq1_results_modules.csv")

# Load Repository-Level Data
if not os.path.exists(rq1_repo_file):
    raise FileNotFoundError(f"Missing required file: {rq1_repo_file}")

df_repo = pd.read_csv(rq1_repo_file)

# Load Module-Level Data (optional backup / per-module analysis)
df_module = None
if os.path.exists(rq1_module_file):
    df_module = pd.read_csv(rq1_module_file)

# -------------------------------------------------------------------
# Data Preprocessing & Metric Normalization
# -------------------------------------------------------------------
# Build Success Numeric Value
df_repo["build_success_num"] = df_repo["build_success"].astype(int)

# Recompute Test Pass Rate if missing or needs recalculation
if "pass_rate" not in df_repo.columns or df_repo["pass_rate"].isna().any():
    df_repo["pass_rate"] = np.where(
        df_repo["total_tests"] > 0,
        (df_repo["total_passed"] / df_repo["total_tests"]) * 100,
        0.0,
    )
else:
    # Clean potential trailing characters (like stray dots) if stored as string/object
    df_repo["pass_rate"] = pd.to_numeric(
        df_repo["pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
    ).fillna(0.0)

# Recompute Equivalence Rate if missing or needs recalculation
if "equivalence_rate" not in df_repo.columns or df_repo["equivalence_rate"].isna().any():
    df_repo["equivalence_rate"] = np.where(
        df_repo["total_modules"] > 0,
        (df_repo["equivalent_modules"] / df_repo["total_modules"]) * 100,
        0.0,
    )
else:
    df_repo["equivalence_rate"] = pd.to_numeric(
        df_repo["equivalence_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
    ).fillna(0.0)

# Sort repositories alphabetically for uniform display
df_repo = df_repo.sort_values(by="repo").reset_index(drop=True)

# Filter out non-repository summary rows if any exist
df_repo_clean = df_repo[
    ~df_repo["repo"].astype(str).str.startswith("RQ1") & 
    ~df_repo["repo"].astype(str).str.startswith("RQ2")
].copy()

# -------------------------------------------------------------------
# Table 1: Per-Repository Breakdown (Single Column)
# -------------------------------------------------------------------
latex_repo_table = """\\begin{table}[htbp]
\\centering
\\caption{Per-Repository Build Success, Test Pass Rate, and Module Equivalence (RQ1)}
\\label{tab:rq1_repo_breakdown}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lrrrr}
\\toprule
\\textbf{Repository} & \\textbf{Modules} & \\textbf{Build Rate} & \\textbf{Test Pass Rate} & \\textbf{Equivalence Rate} \\\\
\\midrule
"""

for _, row in df_repo_clean.iterrows():
    build_status = "\\cmark" if row["build_success_num"] == 1 else "\\xmark"
    latex_repo_table += (
        f"{row['repo']} & "
        f"{int(row['total_modules'])} & "
        f"{build_status} & "
        f"{row['pass_rate']:.1f}\\% & "
        f"{row['equivalence_rate']:.1f}\\% \\\\\n"
    )

latex_repo_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

with open(os.path.join(TABLES_DIR, "rq1_per_repo_breakdown.tex"), "w") as f:
    f.write(latex_repo_table)

print("Saved: rq1_per_repo_breakdown.tex (Single Column Fitted)")

# -------------------------------------------------------------------
# Table 2: Macro Summary & Descriptive Statistics Across All Repositories
# -------------------------------------------------------------------
total_repos = len(df_repo_clean)
total_modules = df_repo_clean["total_modules"].sum()
total_tests = df_repo_clean["total_tests"].sum()

build_success_rate = (df_repo_clean["build_success_num"].mean()) * 100

# Pass Rate Statistics (Mean, Std, Median, IQR, Min, Max)
pass_mean = df_repo_clean["pass_rate"].mean()
pass_std = df_repo_clean["pass_rate"].std()
pass_median = df_repo_clean["pass_rate"].median()
pass_iqr = df_repo_clean["pass_rate"].quantile(0.75) - df_repo_clean["pass_rate"].quantile(0.25)
pass_min = df_repo_clean["pass_rate"].min()
pass_max = df_repo_clean["pass_rate"].max()

# Equivalence Rate Statistics
equiv_mean = df_repo_clean["equivalence_rate"].mean()
equiv_std = df_repo_clean["equivalence_rate"].std()
equiv_median = df_repo_clean["equivalence_rate"].median()
equiv_iqr = df_repo_clean["equivalence_rate"].quantile(0.75) - df_repo_clean["equivalence_rate"].quantile(0.25)
equiv_min = df_repo_clean["equivalence_rate"].min()
equiv_max = df_repo_clean["equivalence_rate"].max()

# Dependency Action Statistics
mean_upgraded = df_repo_clean["upgraded_count"].mean()
mean_added = df_repo_clean["added_count"].mean()

latex_summary_table = f"""\\begin{{table}}[htbp]
\\centering
\\caption{{Macro Summary and Descriptive Statistics of RQ1 Evaluation Metrics ($N = {total_repos}$ Repositories)}}
\\label{{tab:rq1_macro_summary}}
\\resizebox{{\\linewidth}}{{!}}{{%
\\begin{{tabular}}{{lcccc}}
\\toprule
\\textbf{{Metric}} & \\textbf{{Mean $\\pm$ Std}} & \\textbf{{Median [IQR]}} & \\textbf{{Min / Max}} & \\textbf{{Total}} \\\\
\\midrule
Build Success Rate & {build_success_rate:.1f}\\% & -- & -- & {int(df_repo_clean['build_success_num'].sum())}/{total_repos} \\\\
Test Pass Rate & {pass_mean:.1f}\\% $\\pm$ {pass_std:.1f} & {pass_median:.1f}\\% [{pass_iqr:.1f}] & {pass_min:.1f}\\% / {pass_max:.1f}\\% & {total_tests:,} tests \\\\
Module Equivalence Rate & {equiv_mean:.1f}\\% $\\pm$ {equiv_std:.1f} & {equiv_median:.1f}\\% [{equiv_iqr:.1f}] & {equiv_min:.1f}\\% / {equiv_max:.1f}\\% & {total_modules:,} modules \\\\
Added Dependencies / Repo & {mean_added:.2f} & {df_repo_clean['added_count'].median():.1f} & {df_repo_clean['added_count'].min()} / {df_repo_clean['added_count'].max()} & {df_repo_clean['added_count'].sum():,} \\\\
\\bottomrule
\\end{{tabular}}%
}}
\\end{{table}}"""

with open(os.path.join(TABLES_DIR, "rq1_macro_summary.tex"), "w") as f:
    f.write(latex_summary_table)

print("Saved: rq1_macro_summary.tex (Descriptive Statistics Included)")

# # -------------------------------------------------------------------
# # Table 3: Detailed Module Equivalence & Test Statistics (From Module-Level CSV)
# # -------------------------------------------------------------------
# if df_module is not None:
#     module_summary = (
#         df_module.groupby("repo")
#         .agg(
#             modules_count=("module", "count"),
#             build_pass_count=("build_success", lambda x: x.astype(int).sum()),
#             tests_run_total=("tests_run", "sum"),
#             tests_passed_total=("tests_passed", "sum"),
#             equivalent_count=("equivalent", lambda x: x.astype(int).sum()),
#         )
#         .reset_index()
#     )

#     module_summary["mod_build_rate"] = (
#         module_summary["build_pass_count"] / module_summary["modules_count"]
#     ) * 100
#     module_summary["mod_pass_rate"] = np.where(
#         module_summary["tests_run_total"] > 0,
#         (module_summary["tests_passed_total"] / module_summary["tests_run_total"]) * 100,
#         0.0,
#     )
#     module_summary["mod_equiv_rate"] = (
#         module_summary["equivalent_count"] / module_summary["modules_count"]
#     ) * 100

#     latex_module_table = """\\begin{table}[htbp]
# \\centering
# \\caption{Module-Level Aggregated Metrics by Repository (RQ1)}
# \\label{tab:rq1_module_aggregated}
# \\resizebox{\\linewidth}{!}{%
# \\begin{tabular}{lrrrr}
# \\toprule
# \\textbf{Repository} & \\textbf{Modules} & \\textbf{Module Build Rate} & \\textbf{Module Pass Rate} & \\textbf{Module Equivalence} \\\\
# \\midrule
# """

#     for _, row in module_summary.iterrows():
#         latex_module_table += (
#             f"{row['repo']} & "
#             f"{int(row['modules_count'])} & "
#             f"{row['mod_build_rate']:.1f}\\% & "
#             f"{row['mod_pass_rate']:.1f}\\% & "
#             f"{row['mod_equiv_rate']:.1f}\\% \\\\\n"
#         )

#     latex_module_table += """\\bottomrule
# \\end{tabular}%
# }
# \\end{table}"""

#     with open(os.path.join(TABLES_DIR, "rq1_module_aggregated.tex"), "w") as f:
#         f.write(latex_module_table)

#     print("Saved: rq1_module_aggregated.tex (Single Column Fitted)")