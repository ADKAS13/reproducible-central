import os
import numpy as np
import pandas as pd

# Paths setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join("results")
TABLES_DIR = os.path.join(SCRIPT_DIR, "tables")
os.makedirs(TABLES_DIR, exist_ok=True)

FLAGS = ["major", "minor", "patch"]

# -------------------------------------------------------------------
# Data Loading & Processing from Designated CSVs
# -------------------------------------------------------------------
repo_breakdown_by_flag = {}
flag_summary_data = {}

for flag in FLAGS:
    # 1. Load per-repo breakdown for dependency actions & build rates
    repo_file = os.path.join(RESULTS_DIR, f"rq2_breakdown_by_repo_{flag}.csv")
    if os.path.exists(repo_file):
        repo_breakdown_by_flag[flag] = pd.read_csv(repo_file)
    
    # 2. Load per-flag summary aggregates
    summary_file = os.path.join(RESULTS_DIR, "rq2_breakdown_per_flag.csv")
    # Alternatively check flag-specific summary if structured separately, 
    # but rq2_breakdown_per_flag.csv contains all flags with a 'flag' column.

# Load macro summary from rq2_breakdown_per_flag.csv
if os.path.exists(os.path.join(RESULTS_DIR, "rq2_breakdown_per_flag.csv")):
    df_flag_summary = pd.read_csv(os.path.join(RESULTS_DIR, "rq2_breakdown_per_flag.csv"))
else:
    df_flag_summary = pd.DataFrame()

# Get master list of repositories across flag breakdown files
all_repos = []
if repo_breakdown_by_flag:
    sample_df = list(repo_breakdown_by_flag.values())[0]
    all_repos = sorted([r for r in sample_df["repo"].unique() if not str(r).startswith("RQ")])

# -------------------------------------------------------------------
# Table 1: Paginated Longtable (Per-Repository Breakdown)
# -------------------------------------------------------------------
rows = []
for repo in all_repos:
    for flag in FLAGS:
        if flag in repo_breakdown_by_flag:
            df_flag = repo_breakdown_by_flag[flag]
            repo_data = df_flag[df_flag["repo"] == repo]
            if not repo_data.empty:
                r = repo_data.iloc[0]
                # Determine build status mark from build_success_rate or successful_builds
                success_rate = r.get("build_success_rate", 0.0)
                build_mark = "\\cmark" if success_rate >= 100.0 else "\\xmark"
                
                rows.append({
                    "Repository": repo,
                    "Flag": flag.capitalize(),
                    "Upgraded": int(r.get("upgraded", 0)),
                    "Pinned": int(r.get("pinned", 0)),
                    "Downgraded": int(r.get("downgraded", 0)),
                    "Build": build_mark,
                })

df_repo_latex = pd.DataFrame(rows)

latex_repo_table = """\\onecolumn
\\begin{small}
\\setlength{\\tabcolsep}{4pt}
\\begin{longtable}{llrrrr}
\\caption{Per-Repository Dependency Actions and Build Status across Update Flags} \\label{tab:repo_breakdown} \\\\
\\toprule
\\textbf{Repository} & \\textbf{Flag} & \\textbf{Upgraded} & \\textbf{Pinned} & \\textbf{Downgraded} & \\textbf{Build} \\\\
\\midrule
\\endfirsthead

\\multicolumn{6}{c}{{\\tablename\\ \\thetable\\ -- continued from previous page}} \\\\
\\toprule
\\textbf{Repository} & \\textbf{Flag} & \\textbf{Upgraded} & \\textbf{Pinned} & \\textbf{Downgraded} & \\textbf{Build} \\\\
\\midrule
\\endhead

\\midrule
\\multicolumn{6}{r}{{Continued on next page}} \\\\
\\endfoot

\\bottomrule
\\endlastfoot
"""

current_repo = ""
for _, row in df_repo_latex.iterrows():
    repo_str = row["Repository"] if row["Repository"] != current_repo else ""
    if current_repo != "" and row["Repository"] != current_repo:
        latex_repo_table += "\\midrule\n"
    current_repo = row["Repository"]

    latex_repo_table += f"{repo_str} & {row['Flag']} & {row['Upgraded']} & {row['Pinned']} & {row['Downgraded']} & {row['Build']} \\\\\n"

latex_repo_table += """\\end{longtable}
\\end{small}
\\twocolumn"""

with open(os.path.join(TABLES_DIR, "rq2_per_repo_breakdown.tex"), "w") as f:
    f.write(latex_repo_table)

print("Saved: rq2_per_repo_breakdown.tex (Paginated Longtable)")

# -------------------------------------------------------------------
# Load Test Pass Rates Directly from rq1_style_stats_{flag}.csv
# -------------------------------------------------------------------
test_stats = {}
test_stats_dfs = []

# 1. Load RQ1 baseline test stats for comparison
rq1_file = os.path.join(RESULTS_DIR, "rq1_results.csv")
df_rq1_repos = pd.DataFrame({"repo": all_repos})
df_rq1_repos["flag"] = "RQ1"
if os.path.exists(rq1_file):
    df_rq1 = pd.read_csv(rq1_file)
    df_rq1["pass_rate"] = pd.to_numeric(
        df_rq1["pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
    ).fillna(0.0)
    df_rq1_repos = pd.merge(df_rq1_repos, df_rq1[["repo", "pass_rate"]], on="repo", how="left")
else:
    df_rq1_repos["pass_rate"] = 0.0
df_rq1_repos["pass_rate"] = df_rq1_repos["pass_rate"].fillna(0.0)
test_stats_dfs.append(df_rq1_repos[["repo", "pass_rate", "flag"]])

# 2. Load RQ2 flag test stats from rq1_style_stats_{flag}.csv
for flag in FLAGS:
    df_flag_repos = pd.DataFrame({"repo": all_repos})
    df_flag_repos["flag"] = flag.capitalize()
    
    file_path = os.path.join(RESULTS_DIR, f"rq1_style_stats_{flag}.csv")
    if os.path.exists(file_path):
        df_test = pd.read_csv(file_path)
        # Ensure pass_rate is calculated properly from total_passed / total_tests if not present or explicit
        if "pass_rate" not in df_test.columns or df_test["pass_rate"].isna().all():
            df_test["pass_rate"] = np.where(
                df_test["total_tests"] > 0,
                (df_test["total_passed"] / df_test["total_tests"]) * 100,
                0.0
            )
        else:
            df_test["pass_rate"] = pd.to_numeric(df_test["pass_rate"], errors="coerce").fillna(0.0)
            
        df_flag_repos = pd.merge(df_flag_repos, df_test[["repo", "pass_rate"]], on="repo", how="left")
    else:
        df_flag_repos["pass_rate"] = 0.0

    df_flag_repos["pass_rate"] = df_flag_repos["pass_rate"].fillna(0.0)
    
    # Compute authentic mean and std using actual test execution results
    mean_val = df_flag_repos["pass_rate"].mean()
    std_val = df_flag_repos["pass_rate"].std()
    test_stats[flag] = (mean_val, std_val)

    test_stats_dfs.append(df_flag_repos[["repo", "pass_rate", "flag"]])

# -------------------------------------------------------------------
# Table 2: Macro Summary (RQ1-Style with Mean ± Std)
# -------------------------------------------------------------------
s_major = df_flag_summary[df_flag_summary["flag"] == "major"].iloc[0] if not df_flag_summary.empty and not df_flag_summary[df_flag_summary["flag"] == "major"].empty else None
s_minor = df_flag_summary[df_flag_summary["flag"] == "minor"].iloc[0] if not df_flag_summary.empty and not df_flag_summary[df_flag_summary["flag"] == "minor"].empty else None
s_patch = df_flag_summary[df_flag_summary["flag"] == "patch"].iloc[0] if not df_flag_summary.empty and not df_flag_summary[df_flag_summary["flag"] == "patch"].empty else None

def get_val(row, col, default=0.0):
    if row is not None and col in row:
        return row[col]
    return default

latex_summary_table = f"""\\begin{{table}}[htbp]
\\centering
\\caption{{Macro Summary and Descriptive Statistics Across Update Scopes (RQ2)}}
\\label{{tab:rq2_macro_summary}}
\\resizebox{{\\linewidth}}{{!}}{{%
\\begin{{tabular}}{{lccc}}
\\toprule
\\textbf{{Metric}} & \\textbf{{Major}} & \\textbf{{Minor}} & \\textbf{{Patch}} \\\\
\\midrule
Build Success Rate & {get_val(s_major, 'build_success_rate'):.1f}\\% & {get_val(s_minor, 'build_success_rate'):.1f}\\% & {get_val(s_patch, 'build_success_rate'):.1f}\\% \\\\
Test Pass Rate (Mean $\\pm$ Std) & {test_stats['major'][0]:.1f}\\% $\\pm$ {test_stats['major'][1]:.1f} & {test_stats['minor'][0]:.1f}\\% $\\pm$ {test_stats['minor'][1]:.1f} & {test_stats['patch'][0]:.1f}\\% $\\pm$ {test_stats['patch'][1]:.1f} \\\\
Upgraded Dependencies (Total) & {int(get_val(s_major, 'upgraded_total')):,} & {int(get_val(s_minor, 'upgraded_total')):,} & {int(get_val(s_patch, 'upgraded_total')):,} \\\\
Upgraded Dependencies (Mean) & {get_val(s_major, 'upgraded_avg'):.2f} & {get_val(s_minor, 'upgraded_avg'):.2f} & {get_val(s_patch, 'upgraded_avg'):.2f} \\\\
Pinned Dependencies (Mean) & {get_val(s_major, 'pinned_avg'):.2f} & {get_val(s_minor, 'pinned_avg'):.2f} & {get_val(s_patch, 'pinned_avg'):.2f} \\\\
Downgraded Dependencies (Mean) & {get_val(s_major, 'downgraded_avg'):.2f} & {get_val(s_minor, 'downgraded_avg'):.2f} & {get_val(s_patch, 'downgraded_avg'):.2f} \\\\
\\bottomrule
\\end{{tabular}}%
}}
\\end{{table}}"""

with open(os.path.join(TABLES_DIR, "rq2_per_flag_summary.tex"), "w") as f:
    f.write(latex_summary_table)

print("Saved: rq2_per_flag_summary.tex (Macro Summary)")

# -------------------------------------------------------------------
# Table 3: Per-Repository Test Success Rates (Including RQ1)
# -------------------------------------------------------------------
if test_stats_dfs:
    df_test_all = pd.concat(test_stats_dfs, ignore_index=True)

    pivot_test = df_test_all.pivot(
        index="repo", columns="flag", values="pass_rate"
    ).reset_index().fillna(0.0)

    cols = ["repo"] + [c for c in ["RQ1", "Major", "Minor", "Patch"] if c in pivot_test.columns]
    pivot_test = pivot_test[cols]

    latex_test_table = """\\begin{table}[htbp]
\\centering
\\caption{Test Success Rate (\\%) by Repository: RQ1 vs. RQ2 Update Flags}
\\label{tab:test_success_rates}
\\resizebox{\\linewidth}{!}{%
\\begin{tabular}{lrrrr}
\\toprule
\\textbf{Repository} & \\textbf{RQ1 (\\%)} & \\textbf{Major (\\%)} & \\textbf{Minor (\\%)} & \\textbf{Patch (\\%)} \\\\
\\midrule
"""

    for _, row in pivot_test.iterrows():
        rq1_val = f"{row.get('RQ1', 0.0):.1f}\\%"
        major_val = f"{row.get('Major', 0.0):.1f}\\%"
        minor_val = f"{row.get('Minor', 0.0):.1f}\\%"
        patch_val = f"{row.get('Patch', 0.0):.1f}\\%"
        latex_test_table += (
            f"{row['repo']} & {rq1_val} & {major_val} & {minor_val} & {patch_val} \\\\\n"
        )

    latex_test_table += """\\bottomrule
\\end{tabular}%
}
\\end{table}"""

    with open(os.path.join(TABLES_DIR, "rq2_test_success_rates.tex"), "w") as f:
        f.write(latex_test_table)

    print("Saved: rq2_test_success_rates.tex (RQ1 vs RQ2 Test Rates)")