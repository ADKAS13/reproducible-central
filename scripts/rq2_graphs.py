import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Set visual style
sns.set_theme(style="whitegrid")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join("results")
GRAPHS_DIR = os.path.join(SCRIPT_DIR, "graphs")
os.makedirs(GRAPHS_DIR, exist_ok=True)

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
# Data Loading & Preparation
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

# -------------------------------------------------------------------
# 1. Breakdown per Repository (For Each Flag) - Alphabetical
# -------------------------------------------------------------------
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

    # Sort alphabetically
    grouped = grouped.sort_values(by="repo", ascending=True).reset_index(drop=True)
    repo_breakdown_by_flag[flag] = grouped
    
    grouped.to_csv(
        os.path.join(RESULTS_DIR, f"rq2_breakdown_by_repo_{flag}.csv"),
        index=False,
    )

# -------------------------------------------------------------------
# 2. Breakdown per Flag with Averages across Repos/Modules
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

flag_summary.to_csv(
    os.path.join(RESULTS_DIR, "rq2_breakdown_per_flag.csv"), index=False
)

# -------------------------------------------------------------------
# 3. Graph 1: Combined Grouped Horizontal Bar Chart with Numbers (Major vs Minor vs Patch)
# -------------------------------------------------------------------
df_major = repo_breakdown_by_flag.get("major", pd.DataFrame())
df_minor = repo_breakdown_by_flag.get("minor", pd.DataFrame())
df_patch = repo_breakdown_by_flag.get("patch", pd.DataFrame())

if not df_major.empty:
    merged_repo = df_major[["repo"]].copy()
    merged_repo["Major"] = df_major["upgraded"]
    merged_repo["Minor"] = df_minor["upgraded"] if not df_minor.empty else 0
    merged_repo["Patch"] = df_patch["upgraded"] if not df_patch.empty else 0
    
    merged_repo = merged_repo.sort_values(by="repo", ascending=False)
    
    repos = merged_repo["repo"]
    y = np.arange(len(repos))
    height = 0.25

    fig, ax = plt.subplots(figsize=(11, max(7, len(repos) * 0.45)))

    rects1 = ax.barh(y - height, merged_repo["Major"], height, label="Major", color="#4c72b0")
    rects2 = ax.barh(y, merged_repo["Minor"], height, label="Minor", color="#dd8452")
    rects3 = ax.barh(y + height, merged_repo["Patch"], height, label="Patch", color="#55a868")

    ax.bar_label(rects1, fmt="%d", padding=3, fontsize=7)
    ax.bar_label(rects2, fmt="%d", padding=3, fontsize=7)
    ax.bar_label(rects3, fmt="%d", padding=3, fontsize=7)

    ax.set_yticks(y)
    ax.set_yticklabels(repos, fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    
    ax.set_xlabel("Upgraded Dependency Count", fontweight="bold")
    ax.set_ylabel("Repositories", fontweight="bold")
    ax.set_title("Dependency Upgrades by Repository and Flag Scope (RQ2)", fontweight="bold", fontsize=12, pad=15)
    ax.legend(loc="upper right", frameon=True, framealpha=0.9)

    total_maj = merged_repo["Major"].sum()
    total_min = merged_repo["Minor"].sum()
    total_pat = merged_repo["Patch"].sum()
    
    stats_text = (
        f"Macro Summary:\n"
        f"• Total Major Upgrades: {total_maj}\n"
        f"• Total Minor Upgrades: {total_min}\n"
        f"• Total Patch Upgrades: {total_pat}\n"
        f"• Mean (Major/Minor/Patch): {merged_repo['Major'].mean():.1f} / {merged_repo['Minor'].mean():.1f} / {merged_repo['Patch'].mean():.1f}"
    )
    
    props = dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9, edgecolor="#ccc")
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment="top", bbox=props)

    plt.tight_layout()
    plt.savefig(
        os.path.join(GRAPHS_DIR, "rq2_repo_dependency_breakdown.png"),
        dpi=300,
        bbox_inches="tight",
    )
    plt.close()

# -------------------------------------------------------------------
# Graph 2: Comparison of Modifications Across Flags (Macro View with Numbers)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5))
actions = ["upgraded", "pinned", "downgraded", "added", "removed"]
df_flag_melted = flag_summary.melt(
    id_vars=["flag"],
    value_vars=[f"{a}_avg" for a in actions],
    var_name="action",
    value_name="avg_count",
)
df_flag_melted["action"] = (
    df_flag_melted["action"].str.replace("_avg", "").str.capitalize()
)

sns.barplot(
    data=df_flag_melted,
    x="flag",
    y="avg_count",
    hue="action",
    palette="muted",
    ax=ax,
)

for container in ax.containers:
    ax.bar_label(container, fmt="%.1f", padding=3, fontsize=8, fontweight="bold")

ax.set_ylabel("Average Actions per Module", fontweight="bold")
ax.set_xlabel("Update Flag Scope", fontweight="bold")
ax.set_title("Average Dependency Actions Across Update Flags", fontweight="bold", pad=15)
ax.legend(title="Action", loc="upper left", bbox_to_anchor=(1.02, 1.0))

plt.tight_layout()
plt.savefig(
    os.path.join(GRAPHS_DIR, "rq2_flag_action_comparison.png"), dpi=300, bbox_inches="tight"
)
plt.close()

# -------------------------------------------------------------------
# Helper for Horizontal Alphabetical Per-Repo Charts with Mean & Median
# -------------------------------------------------------------------
def plot_horizontal_repo_success(df_grouped, title, metric_col, output_path, xlabel):
    df_sorted = df_grouped.sort_values(by="repo", ascending=False)
    
    fig, ax = plt.subplots(figsize=(10, max(6, len(df_sorted) * 0.35)))
    
    bars = ax.barh(df_sorted["repo"], df_sorted[metric_col], color="#4c72b0", height=0.6)
    ax.invert_yaxis()
    
    mean_val = df_sorted[metric_col].mean()
    median_val = df_sorted[metric_col].median()
    
    ax.axvline(mean_val, color="#c44e52", linestyle="--", linewidth=1.5, label=f"Mean: {mean_val:.1f}%")
    ax.axvline(median_val, color="#55a868", linestyle=":", linewidth=1.5, label=f"Median: {median_val:.1f}%")
    
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
    
    ax.set_title(title, fontweight="bold", fontsize=12, pad=15)
    ax.set_xlabel(xlabel, fontweight="bold")
    ax.set_ylabel("Repository", fontweight="bold")
    ax.legend(loc="lower right", frameon=True, framealpha=0.9)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

# -------------------------------------------------------------------
# Graph 3: Horizontal Build Success Rate per Repository (Major)
# -------------------------------------------------------------------
if "major" in repo_breakdown_by_flag:
    plot_horizontal_repo_success(
        repo_breakdown_by_flag["major"],
        title="Build Success Rate by Repository (Major Scope)",
        metric_col="build_success_rate",
        output_path=os.path.join(GRAPHS_DIR, "rq2_build_success_rate.png"),
        xlabel="Build Success Rate (%)"
    )
# -------------------------------------------------------------------
# Graph 4: Horizontal Test Success Rate Comparison (RQ1 vs. Major vs. Minor vs. Patch)
# -------------------------------------------------------------------
test_stats_dfs = []

# Load RQ1 results for comparison
rq1_file = os.path.join(RESULTS_DIR, "rq1_results.csv")
if os.path.exists(rq1_file):
    df_rq1_test = pd.read_csv(rq1_file)
    df_rq1_test["flag"] = "RQ1"
    if "pass_rate" not in df_rq1_test.columns:
        df_rq1_test["pass_rate"] = np.where(
            df_rq1_test["total_tests"] > 0,
            (df_rq1_test["total_passed"] / df_rq1_test["total_tests"]) * 100,
            0.0,
        )
    test_stats_dfs.append(df_rq1_test[["repo", "pass_rate", "flag"]])

# Load RQ2 flag test results
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
        test_stats_dfs.append(df_test[["repo", "pass_rate", "flag"]])

if test_stats_dfs:
    df_test_all = pd.concat(test_stats_dfs, ignore_index=True)
    repos_list_test = sorted(df_test_all["repo"].unique())
    y_test = np.arange(len(repos_list_test))
    
    flags_to_plot = ["RQ1", "Major", "Minor", "Patch"]
    height = 0.20
    colors = ["#4c72b0", "#dd8452", "#55a868", "#8172b3"]
    
    fig, ax = plt.subplots(figsize=(11, max(7, len(repos_list_test) * 0.5)))
    
    for i, flag in enumerate(flags_to_plot):
        flag_df = df_test_all[df_test_all["flag"] == flag]
        flag_df = flag_df.set_index("repo").reindex(repos_list_test).reset_index()
        test_rates = flag_df["pass_rate"].fillna(0)

        offset = (i - 1.5) * height
        bars = ax.barh(
            y_test + offset, test_rates, height, label=flag, color=colors[i % len(colors)], alpha=0.9
        )

        # Add explicit numerical labels formatted to 2 decimal places
        ax.bar_label(bars, fmt="%.2f%%", padding=3, fontsize=6)

    # Add vertical reference lines for overall mean and median test pass rate (formatted to 2 decimal places)
    overall_mean = df_test_all["pass_rate"].mean()
    overall_median = df_test_all["pass_rate"].median()
    
    ax.axvline(overall_mean, color="#c44e52", linestyle="--", linewidth=1.5, label=f"Mean: {overall_mean:.2f}%")
    ax.axvline(overall_median, color="#55a868", linestyle=":", linewidth=1.5, label=f"Median: {overall_median:.2f}%")

    ax.set_yticks(y_test)
    ax.set_yticklabels(repos_list_test, fontsize=9, fontweight="bold")
    ax.invert_yaxis()  # Enforce alphabetical A-Z order from top to bottom
    
    ax.set_xlabel("Test Success Rate (%)", fontweight="bold")
    ax.set_ylabel("Repositories", fontweight="bold")
    ax.set_title("Test Success Rate by Repository: RQ1 vs. RQ2 (Major, Minor, Patch)", fontweight="bold", fontsize=12, pad=15)
    ax.set_xlim(0, 125)
    ax.legend(loc="lower right", frameon=True, framealpha=0.9)

    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "rq2_test_success_rate.png"), dpi=300, bbox_inches="tight")
    plt.close()
    print("Saved horizontal test success rate comparison chart with 2-decimal formatting.")

# -------------------------------------------------------------------
# Graph 5: Dual-Axis Graph (All Lines: Build/Test Success vs Upgraded Dependencies)
# -------------------------------------------------------------------
macro_rates = []
for flag in ["major", "minor", "patch"]:
    build_rate = flag_summary.loc[flag_summary["flag"] == flag, "build_success_rate"].values[0]
    upg_avg = flag_summary.loc[flag_summary["flag"] == flag, "upgraded_avg"].values[0]
    
    test_rate = 0.0
    if test_stats_dfs:
        f_df = df_test_all[df_test_all["flag"] == flag.capitalize()]
        if not f_df.empty and "pass_rate" in f_df.columns:
            test_rate = f_df["pass_rate"].mean()

    macro_rates.append({
        "flag": flag.capitalize(),
        "build_success_rate": build_rate,
        "test_pass_rate": test_rate,
        "upgraded_avg": upg_avg
    })

df_macro = pd.DataFrame(macro_rates)

fig, ax1 = plt.subplots(figsize=(9, 5))

x_idx = np.arange(len(df_macro))

# Left Y Axis Lines: Build and Test Success Rates
line1 = ax1.plot(
    x_idx, df_macro["build_success_rate"], 
    color="#4c72b0", marker="s", linewidth=2.5, markersize=8, label="Build Success Rate (%)"
)
line2 = ax1.plot(
    x_idx, df_macro["test_pass_rate"], 
    color="#55a868", marker="^", linewidth=2.5, markersize=8, label="Test Success Rate (%)"
)

ax1.set_xlabel("Version Flag Scope", fontweight="bold")
ax1.set_ylabel("Success Rate (%)", fontweight="bold", color="#2b2b2b")
ax1.set_xticks(x_idx)
ax1.set_xticklabels(df_macro["flag"])
ax1.set_ylim(0, 105)

# Right Y Axis Line: Average Upgraded Dependencies
ax2 = ax1.twinx()
line3 = ax2.plot(
    x_idx, df_macro["upgraded_avg"], 
    color="#c44e52", marker="o", linewidth=2.5, markersize=8, linestyle="--", label="Avg Upgraded Deps"
)
ax2.set_ylabel("Average Upgraded Dependencies / Module", fontweight="bold", color="#c44e52")
ax2.tick_params(axis="y", labelcolor="#c44e52")
ax2.grid(False)

# Add value annotations directly above data points for clarity
for i in range(len(df_macro)):
    ax1.text(i, df_macro["build_success_rate"][i] + 2, f"{df_macro['build_success_rate'][i]:.2f}%", color="#4c72b0", fontweight="bold", ha="center")
    ax1.text(i, df_macro["test_pass_rate"][i] - 5, f"{df_macro['test_pass_rate'][i]:.2f}%", color="#55a868", fontweight="bold", ha="center")
    ax2.text(i, df_macro["upgraded_avg"][i] + (df_macro["upgraded_avg"].max() * 0.03), f"{df_macro['upgraded_avg'][i]:.2f}", color="#c44e52", fontweight="bold", ha="center")

# Consolidate legend and move outside plot box to avoid overlapping content
lines = line1 + line2 + line3
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc="upper left", bbox_to_anchor=(1.15, 1.0), borderaxespad=0.0)

plt.title("Build/Test Success vs. Upgraded Dependencies by Flag Scope", fontweight="bold", pad=15)
plt.tight_layout()
plt.savefig(os.path.join(GRAPHS_DIR, "rq2_dual_axis_success_vs_upgrades.png"), dpi=300, bbox_inches="tight")
plt.close()


# -------------------------------------------------------------------
# Graph 6: Pareto Front Trade-off Analysis (Upgraded Deps vs Pass Rate)
# -------------------------------------------------------------------
pareto_data = []
for flag in FLAGS:
    file_path = os.path.join(RESULTS_DIR, f"rq1_style_stats_{flag}_modules.csv")
    if os.path.exists(file_path):
        m_df = pd.read_csv(file_path)
        m_df["flag"] = flag.capitalize()
        pareto_data.append(m_df)

if pareto_data:
    df_modules_all = pd.concat(pareto_data, ignore_index=True)
    
    fig, ax = plt.subplots(figsize=(9, 6))
    
    sns.scatterplot(
        data=df_modules_all,
        x="upgraded",
        y="pass_rate",
        hue="flag",
        style="flag",
        alpha=0.7,
        s=70,
        ax=ax
    )

    pareto_pts = df_modules_all[["upgraded", "pass_rate"]].drop_duplicates().values
    is_pareto = np.ones(pareto_pts.shape[0], dtype=bool)
    for i, c in enumerate(pareto_pts):
        if is_pareto[i]:
            is_pareto[is_pareto] = np.any(pareto_pts[is_pareto] > c, axis=1) | np.any(pareto_pts[is_pareto] == c, axis=1)
            is_pareto[i] = True

    pareto_front = pareto_pts[is_pareto]
    pareto_front = pareto_front[pareto_front[:, 0].argsort()]

    ax.plot(pareto_front[:, 0], pareto_front[:, 1], color="black", linestyle="--", linewidth=1.5, label="Pareto Frontier")

    ax.set_title("Pareto Frontier: Upgraded Dependencies vs. Test Pass Rate", fontweight="bold")
    ax.set_xlabel("Upgraded Dependencies Count", fontweight="bold")
    ax.set_ylabel("Test Pass Rate (%)", fontweight="bold")
    ax.legend(loc="lower left")

    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "rq2_pareto_upgrades_vs_passrate.png"), dpi=300)
    plt.close()

# -------------------------------------------------------------------
# Graph 7: Distribution Analysis (Box/Violin Plot of Upgraded Deps)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

sns.boxplot(
    data=df_all,
    x="flag",
    y="upgraded",
    palette="Set2",
    showmeans=True,
    meanprops={"marker": "o", "markerfacecolor": "white", "markeredgecolor": "black"},
    ax=ax
)

ax.set_xticklabels([f.capitalize() for f in FLAGS])
ax.set_title("Distribution & Outliers of Upgraded Dependencies per Module", fontweight="bold")
ax.set_xlabel("Version Flag Scope", fontweight="bold")
ax.set_ylabel("Upgraded Dependency Count", fontweight="bold")

plt.tight_layout()
plt.savefig(os.path.join(GRAPHS_DIR, "rq2_upgraded_distribution_box.png"), dpi=300)
plt.close()