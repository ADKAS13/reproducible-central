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
# 1. Build Success Numeric Value
df_repo["build_success_num"] = df_repo["build_success"].astype(int)

# 2. Recompute Test Pass Rate if missing or needs recalculation
if "pass_rate" not in df_repo.columns or df_repo["pass_rate"].isna().any():
    df_repo["pass_rate"] = np.where(
        df_repo["total_tests"] > 0,
        (df_repo["total_passed"] / df_repo["total_tests"]) * 100,
        0.0,
    )

# 3. Recompute Equivalence Rate if missing or needs recalculation
if "equivalence_rate" not in df_repo.columns or df_repo["equivalence_rate"].isna().any():
    df_repo["equivalence_rate"] = np.where(
        df_repo["total_modules"] > 0,
        (df_repo["equivalent_modules"] / df_repo["total_modules"]) * 100,
        0.0,
    )

# Sort repositories alphabetically for uniform display
df_repo = df_repo.sort_values(by="repo").reset_index(drop=True)

# -------------------------------------------------------------------
# Table 1: Per-Repository Breakdown (Single Column)
# -------------------------------------------------------------------
# Filter out non-repository summary rows if any exist
df_repo_clean = df_repo[
    ~df_repo["repo"].astype(str).str.startswith("RQ1") & 
    ~df_repo["repo"].astype(str).str.startswith("RQ2")
].copy()

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
    build_rate = 100.0 if row["build_success_num"] == 1 else 0.0
    latex_repo_table += (
        f"{row['repo']} & "
        f"{int(row['total_modules'])} & "
        f"{build_rate:.1f}\\% & "
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
# Table 2: Macro Summary Across All Repositories (Single Column)
# -------------------------------------------------------------------
total_repos = len(df_repo)
successful_builds = df_repo["build_success_num"].sum()
overall_build_rate = (
    (successful_builds / total_repos) * 100 if total_repos > 0 else 0.0
)

total_tests = df_repo["total_tests"].sum()
total_passed_tests = df_repo["total_passed"].sum()
overall_pass_rate = (
    (total_passed_tests / total_tests) * 100 if total_tests > 0 else 0.0
)

total_modules = df_repo["total_modules"].sum()
total_equivalent_modules = df_repo["equivalent_modules"].sum()
overall_equivalence_rate = (
    (total_equivalent_modules / total_modules) * 100
    if total_modules > 0
    else 0.0
)

latex_summary_table = f"""\\begin{{table}}[htbp]
\\centering
\\caption{{Macro Summary of RQ1 Evaluation Metrics Across All Repositories}}
\\label{{tab:rq1_macro_summary}}
\\resizebox{{\\linewidth}}{{!}}{{%
\\begin{{tabular}}{{lrrrr}}
\\toprule
\\textbf{{Total Repos}} & \\textbf{{Total Modules}} & \\textbf{{Build Success Rate}} & \\textbf{{Test Pass Rate}} & \\textbf{{Equivalence Rate}} \\\\
\\midrule
{total_repos} & {total_modules} & {overall_build_rate:.1f}\\% & {overall_pass_rate:.1f}\\% & {overall_equivalence_rate:.1f}\\% \\\\
\\bottomrule
\\end{{tabular}}%
}}
\\end{{table}}"""

with open(os.path.join(TABLES_DIR, "rq1_macro_summary.tex"), "w") as f:
    f.write(latex_summary_table)

print("Saved: rq1_macro_summary.tex (Single Column Fitted)")
# -------------------------------------------------------------------
# Table 3: Detailed Module Equivalence & Test Statistics (From Module-Level CSV)
# -------------------------------------------------------------------
if df_module is not None:
    # Aggregating metrics per repository from module-level details
    module_summary = (
        df_module.groupby("repo")
        .agg(
            modules_count=("module", "count"),
            build_pass_count=("build_success", lambda x: x.astype(int).sum()),
            tests_run_total=("tests_run", "sum"),
            tests_passed_total=("tests_passed", "sum"),
            equivalent_count=("equivalent", lambda x: x.astype(int).sum()),
        )
        .reset_index()
    )

    module_summary["mod_build_rate"] = (
        module_summary["build_pass_count"] / module_summary["modules_count"]
    ) * 100
    module_summary["mod_pass_rate"] = np.where(
        module_summary["tests_run_total"] > 0,
        (module_summary["tests_passed_total"] / module_summary["tests_run_total"]) * 100,
        0.0,
    )
    module_summary["mod_equiv_rate"] = (
        module_summary["equivalent_count"] / module_summary["modules_count"]
    ) * 100

    latex_module_table = """\\begin{table}[htbp]
\\centering
\\caption{Module-Level Aggregated Metrics by Repository (RQ1)}
\\label{tab:rq1_module_aggregated}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lrrrr}
\\toprule
\\textbf{Repository} & \\textbf{Modules} & \\textbf{Module Build Rate} & \\textbf{Module Pass Rate} & \\textbf{Module Equivalence} \\\\
\\midrule
"""

    for _, row in module_summary.iterrows():
        latex_module_table += (
            f"{row['repo']} & "
            f"{int(row['modules_count'])} & "
            f"{row['mod_build_rate']:.1f}\\% & "
            f"{row['mod_pass_rate']:.1f}\\% & "
            f"{row['mod_equiv_rate']:.1f}\\% \\\\\n"
        )

    latex_module_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

    with open(os.path.join(TABLES_DIR, "rq1_module_aggregated.tex"), "w") as f:
        f.write(latex_module_table)

    print("Saved: rq1_module_aggregated.tex (Single Column Fitted)")