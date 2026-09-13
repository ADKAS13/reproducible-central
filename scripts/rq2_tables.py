import os
import numpy as np
import pandas as pd

# Paths setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join("results")
TABLES_DIR = os.path.join(SCRIPT_DIR, "tables")
os.makedirs(TABLES_DIR, exist_ok=True)

FLAGS = ["major", "minor", "patch"]
NUMERIC_COLS = [
    "pinned",
    "upgraded",
    "downgraded",
    "added",
    "removed",
    "scope_changed",
    "total_before",
    "total_after",
]

# -------------------------------------------------------------------
# Data Loading & Processing
# -------------------------------------------------------------------
flag_dfs = {}
for flag in FLAGS:
    file_path = os.path.join(RESULTS_DIR, f"rq2_results_{flag}.csv")
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        df["flag"] = flag
        df["build_success_num"] = df["build_success"].astype(int)
        flag_dfs[flag] = df

df_all = pd.concat(flag_dfs.values(), ignore_index=True)

# 1. Per-Repo Breakdown for each Flag
repo_breakdown_by_flag = {}
for flag, df in flag_dfs.items():
    grouped = (
        df.groupby("repo")
        .agg(
            {
                **{col: "sum" for col in NUMERIC_COLS},
                "build_success_num": [
                    "count",
                    "sum",
                    lambda x: (x.sum() / x.count()) * 100,
                ],
            }
        )
        .reset_index()
    )
    grouped.columns = [
        "repo",
        *NUMERIC_COLS,
        "total_modules",
        "successful_builds",
        "build_success_rate",
    ]
    repo_breakdown_by_flag[flag] = grouped

# -------------------------------------------------------------------
# Table 1: Spans both columns using table*
# -------------------------------------------------------------------
rows = []
all_repos = sorted(df_all["repo"].unique())

for repo in all_repos:
    for flag in FLAGS:
        data = repo_breakdown_by_flag[flag]
        repo_data = data[data["repo"] == repo]
        if not repo_data.empty:
            r = repo_data.iloc[0]
            rows.append(
                {
                    "Repository": repo,
                    "Flag": flag.capitalize(),
                    "Upgraded": int(r["upgraded"]),
                    "Pinned": int(r["pinned"]),
                    "Downgraded": int(r["downgraded"]),
                    "Build Success Rate": f"{r['build_success_rate']:.1f}\\%",
                }
            )

df_repo_latex = pd.DataFrame(rows)

latex_repo_table = """\\begin{table*}[t]
\\centering
\\caption{Per-Repository Dependency Actions and Build Success Rate across Update Flags}
\\label{tab:repo_breakdown}
\\begin{tabular}{llrrrr}
\\toprule
\\textbf{Repository} & \\textbf{Flag} & \\textbf{Upgraded} & \\textbf{Pinned} & \\textbf{Downgraded} & \\textbf{Build Success Rate} \\\\
\\midrule
"""

current_repo = ""
for idx, row in df_repo_latex.iterrows():
    repo_str = row["Repository"] if row["Repository"] != current_repo else ""
    if current_repo != "" and row["Repository"] != current_repo:
        latex_repo_table += "\\midrule\n"
    current_repo = row["Repository"]

    latex_repo_table += f"{repo_str} & {row['Flag']} & {row['Upgraded']} & {row['Pinned']} & {row['Downgraded']} & {row['Build Success Rate']} \\\\\n"

latex_repo_table += """\\bottomrule
\\end{tabular}
\\end{table*}"""

with open(os.path.join(TABLES_DIR, "rq2_per_repo_breakdown.tex"), "w") as f:
    f.write(latex_repo_table)

print("Saved: rq2_per_repo_breakdown.tex (Full-Width / Two-Column)")

# -------------------------------------------------------------------
# Table 2: Single Column auto-scaled with \resizebox
# -------------------------------------------------------------------
flag_summary = (
    df_all.groupby("flag")
    .agg(
        {
            **{col: ["sum", "mean"] for col in NUMERIC_COLS},
            "build_success_num": [
                "count",
                "sum",
                lambda x: (x.sum() / x.count()) * 100,
            ],
        }
    )
    .reset_index()
)

flag_summary.columns = [
    "flag",
    "pinned_total",
    "pinned_avg",
    "upgraded_total",
    "upgraded_avg",
    "downgraded_total",
    "downgraded_avg",
    "added_total",
    "added_avg",
    "removed_total",
    "removed_avg",
    "scope_changed_total",
    "scope_changed_avg",
    "total_before_sum",
    "total_before_avg",
    "total_after_sum",
    "total_after_avg",
    "total_modules",
    "successful_builds",
    "build_success_rate",
]

latex_summary_table = """\\begin{table}[htbp]
\\centering
\\caption{Macro Summary of Dependency Actions and Average Actions per Module}
\\label{tab:flag_summary}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lrrrrr}
\\toprule
\\textbf{Flag} & \\textbf{Upgraded Total} & \\textbf{Upgraded Avg} & \\textbf{Pinned Avg} & \\textbf{Downgraded Avg} & \\textbf{Build Success Rate} \\\\
\\midrule
"""

for _, row in flag_summary.iterrows():
    latex_summary_table += (
        f"{row['flag'].capitalize()} & "
        f"{int(row['upgraded_total'])} & "
        f"{row['upgraded_avg']:.2f} & "
        f"{row['pinned_avg']:.2f} & "
        f"{row['downgraded_avg']:.2f} & "
        f"{row['build_success_rate']:.1f}\\% \\\\\n"
    )

latex_summary_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

with open(os.path.join(TABLES_DIR, "rq2_per_flag_summary.tex"), "w") as f:
    f.write(latex_summary_table)

print("Saved: rq2_per_flag_summary.tex (Single Column Fitted)")

# -------------------------------------------------------------------
# Table 3: Single Column Test Success Rates
# -------------------------------------------------------------------
test_stats_dfs = []
for flag in FLAGS:
    file_path = os.path.join(RESULTS_DIR, f"rq1_style_stats_{flag}.csv")
    if os.path.exists(file_path):
        df_test = pd.read_csv(file_path)
        df_test["flag"] = flag.capitalize()
        if "pass_rate" not in df_test.columns:
            df_test["pass_rate"] = np.where(
                df_test["total_tests"] > 0,
                (df_test["total_passed"] / df_test["total_tests"]) * 100,
                0.0,
            )
        test_stats_dfs.append(df_test)

if test_stats_dfs:
    df_test_all = pd.concat(test_stats_dfs, ignore_index=True)

    pivot_test = df_test_all.pivot(
        index="repo", columns="flag", values="pass_rate"
    ).reset_index()

    latex_test_table = """\\begin{table}[htbp]
\\centering
\\caption{Test Success Rate (\\%) by Repository across Update Flags}
\\label{tab:test_success_rates}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lrrr}
\\toprule
\\textbf{Repository} & \\textbf{Major (\\%)} & \\textbf{Minor (\\%)} & \\textbf{Patch (\\%)} \\\\
\\midrule
"""

    for _, row in pivot_test.iterrows():
        major_val = f"{row.get('Major', 0.0):.1f}\\%"
        minor_val = f"{row.get('Minor', 0.0):.1f}\\%"
        patch_val = f"{row.get('Patch', 0.0):.1f}\\%"
        latex_test_table += (
            f"{row['repo']} & {major_val} & {minor_val} & {patch_val} \\\\\n"
        )

    latex_test_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

    with open(os.path.join(TABLES_DIR, "rq2_test_success_rates.tex"), "w") as f:
        f.write(latex_test_table)

    print("Saved: rq2_test_success_rates.tex (Single Column Fitted)")