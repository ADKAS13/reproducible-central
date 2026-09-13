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
        ax.bar(
            repos,
            values,
            bottom=bottom,
            label=action.capitalize(),
            color=color,
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