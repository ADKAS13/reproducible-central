import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Set visual style
csv_path = os.path.join("results", "rq1_results.csv")
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
        # Convert build_success to numeric boolean/percentage float if needed
        df["build_success_num"] = df["build_success"].astype(int)
        flag_dfs[flag] = df

df_all = pd.concat(flag_dfs.values(), ignore_index=True)

# -------------------------------------------------------------------
# 1. Breakdown per Repository (For Each Flag)
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

    # Flatten column multi-index
    grouped.columns = [
        "repo",
        *NUMERIC_COLS,
        "total_modules",
        "successful_builds",
        "build_success_rate",
    ]

    repo_breakdown_by_flag[flag] = grouped
    grouped.to_csv(
        os.path.join(RESULTS_DIR, f"rq2_breakdown_by_repo_{flag}.csv"),
        index=False,
    )
    print(f"--- Per-Repo Breakdown for Flag: {flag.upper()} ---")
    print(grouped[["repo", "upgraded", "pinned", "downgraded", "build_success_rate"]])
    print("\n")

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

# Flatten MultiIndex columns
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
print("--- Per-Flag Summary & Averages ---")
print(
    flag_summary[
        [
            "flag",
            "upgraded_total",
            "upgraded_avg",
            "pinned_avg",
            "downgraded_avg",
            "build_success_rate",
        ]
    ]
)

# -------------------------------------------------------------------
# 3. Graph 1: Stacked Dependency Actions Breakdown per Repo & Flag
# -------------------------------------------------------------------
fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=True)

actions = ["upgraded", "pinned", "downgraded", "added", "removed"]
colors = ["#55a868", "#4c72b0", "#ccb974", "#8172b0", "#c44e52"]

for idx, flag in enumerate(FLAGS):
    ax = axes[idx]
    data = repo_breakdown_by_flag[flag]
    repos = data["repo"]

    bottom = np.zeros(len(repos))
    for action, color in zip(actions, colors):
        values = data[action]
        bars = ax.bar(
            repos,
            values,
            bottom=bottom,
            label=action.capitalize(),
            color=color,
        )

        # Add quantity labels inside each bar segment
        for bar, val, btm in zip(bars, values, bottom):
            if val > 0:  # Only label non-zero values to avoid clutter
                # Position text in the vertical center of the segment
                y_pos = btm + (val / 2.0)
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    y_pos,
                    f"{int(val)}",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=8,
                    fontweight="bold",
                )

        bottom += values

    ax.set_title(f"Flag: {flag.capitalize()}", fontweight="bold")
    ax.set_xlabel("Repositories", fontweight="bold")
    ax.tick_params(axis="x", rotation=45)
    if idx == 0:
        ax.set_ylabel("Dependency Action Count", fontweight="bold")
        ax.legend(loc="upper left")

plt.suptitle(
    "Dependency Modifications Breakdown by Repository and Flag (RQ2)",
    fontweight="bold",
    fontsize=14,
    y=1.02,
)
plt.tight_layout()
plt.savefig(
    os.path.join(GRAPHS_DIR, "rq2_repo_dependency_breakdown.png"),
    dpi=300,
    bbox_inches="tight",
)
plt.close()

# -------------------------------------------------------------------
# Graph 2: Comparison of Modifications Across Flags (Macro View)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5))

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

ax.set_ylabel("Average Actions per Module", fontweight="bold")
ax.set_xlabel("Update Flag Scope", fontweight="bold")
ax.set_title(
    "Average Dependency Actions Across Update Flags", fontweight="bold"
)
ax.legend(title="Action", loc="upper left")

plt.tight_layout()
plt.savefig(
    os.path.join(GRAPHS_DIR, "rq2_flag_action_comparison.png"), dpi=300
)
plt.close()

# -------------------------------------------------------------------
# Graph 3: Build Success Rate per Repository across Flags
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5))

# Prepare grouped data for build success rates
success_data = []
for flag, df_grouped in repo_breakdown_by_flag.items():
    for _, row in df_grouped.iterrows():
        success_data.append(
            {
                "repo": row["repo"],
                "flag": flag.capitalize(),
                "pass_rate": row["build_success_rate"],
            }
        )
df_success = pd.DataFrame(success_data)

x = np.arange(len(df_success["repo"].unique()))
repos_list = df_success["repo"].unique()
width = 0.25

for i, flag in enumerate(["Major", "Minor", "Patch"]):
    flag_rates = df_success[df_success["flag"] == flag]["pass_rate"]
    offset = (i - 1) * width
    bars = ax.bar(
        x + offset, flag_rates, width, label=f"{flag} Flag", alpha=0.9
    )

    # Annotate bar percentages
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + 1.5,
            f"{height:.0f}%",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
        )

ax.set_ylabel("Build Success Rate (%)", fontweight="bold")
ax.set_xlabel("Repositories", fontweight="bold")
ax.set_title(
    "Build Success Rate by Repository and Flag Scope", fontweight="bold"
)
ax.set_xticks(x)
ax.set_xticklabels(repos_list, rotation=30, ha="right")
ax.set_ylim(0, 115)
ax.legend(loc="upper left")

plt.tight_layout()
plt.savefig(os.path.join(GRAPHS_DIR, "rq2_build_success_rate.png"), dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 4: Test Success Rate per Repository across Flags
# -------------------------------------------------------------------
test_stats_dfs = []
for flag in FLAGS:
    file_path = os.path.join(RESULTS_DIR, f"rq1_style_stats_{flag}.csv")
    if os.path.exists(file_path):
        df_test = pd.read_csv(file_path)
        df_test["flag"] = flag.capitalize()
        # Compute pass_rate (%) if not present, otherwise use existing
        if "pass_rate" not in df_test.columns:
            df_test["pass_rate"] = np.where(
                df_test["total_tests"] > 0,
                (df_test["total_passed"] / df_test["total_tests"]) * 100,
                0.0,
            )
        test_stats_dfs.append(df_test)

if test_stats_dfs:
    df_test_all = pd.concat(test_stats_dfs, ignore_index=True)

    fig, ax = plt.subplots(figsize=(10, 5))

    repos_list_test = df_test_all["repo"].unique()
    x_test = np.arange(len(repos_list_test))
    width = 0.25

    for i, flag in enumerate(["Major", "Minor", "Patch"]):
        flag_df = df_test_all[df_test_all["flag"] == flag]
        
        # Ensure alignment with repos_list_test order
        flag_df = flag_df.set_index("repo").reindex(repos_list_test).reset_index()
        test_rates = flag_df["pass_rate"].fillna(0)

        offset = (i - 1) * width
        bars = ax.bar(
            x_test + offset, test_rates, width, label=f"{flag} Flag", alpha=0.9
        )

        # Annotate bar percentages
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                height + 1.5,
                f"{height:.0f}%",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
            )

    ax.set_ylabel("Test Success Rate (%)", fontweight="bold")
    ax.set_xlabel("Repositories", fontweight="bold")
    ax.set_title(
        "Test Success Rate by Repository and Flag Scope", fontweight="bold"
    )
    ax.set_xticks(x_test)
    ax.set_xticklabels(repos_list_test, rotation=30, ha="right")
    ax.set_ylim(0, 115)
    ax.legend(loc="upper left")

    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, "rq2_test_success_rate.png"), dpi=300)
    plt.close()

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
        tot_tests = f_df["total_tests"].sum()
        tot_passed = f_df["total_passed"].sum()
        test_rate = (tot_passed / tot_tests * 100) if tot_tests > 0 else f_df["pass_rate"].mean()

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
    ax1.text(i, df_macro["build_success_rate"][i] + 2, f"{df_macro['build_success_rate'][i]:.1f}%", color="#4c72b0", fontweight="bold", ha="center")
    ax1.text(i, df_macro["test_pass_rate"][i] - 4, f"{df_macro['test_pass_rate'][i]:.1f}%", color="#55a868", fontweight="bold", ha="center")
    ax2.text(i, df_macro["upgraded_avg"][i] + (df_macro["upgraded_avg"].max() * 0.03), f"{df_macro['upgraded_avg'][i]:.1f}", color="#c44e52", fontweight="bold", ha="center")

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