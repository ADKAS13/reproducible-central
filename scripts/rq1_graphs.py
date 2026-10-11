import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# -------------------------------------------------------------------
# Paths & Data Loading Setup
# -------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join("results")
os.makedirs("graphs", exist_ok=True)

rq1_csv_path = os.path.join(RESULTS_DIR, "rq1_results.csv")
base_csv_path = os.path.join(RESULTS_DIR, "base_results.csv")

if not os.path.exists(rq1_csv_path):
    raise FileNotFoundError(f"Missing required file: {rq1_csv_path}")

df_rq1 = pd.read_csv(rq1_csv_path)

# Clean and sort RQ1 data alphabetically A-Z
df_rq1["pass_rate"] = pd.to_numeric(
    df_rq1["pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
).fillna(0.0)
df_rq1 = df_rq1.sort_values(by="repo", ascending=False).reset_index(drop=True)

sns.set_theme(style="whitegrid")

# Dynamic figure height based on repository count to prevent crowding
fig_height = max(6, len(df_rq1) * 0.4)

# -------------------------------------------------------------------
# Graph 1: Stacked Dependency Actions Breakdown (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, fig_height))

repos = df_rq1["repo"]
upgraded = df_rq1["upgraded_count"]
added = df_rq1["added_count"]
removed = df_rq1["removed_count"]
downgraded = df_rq1["downgraded_count"]

# Horizontal Stacked Bars
ax.barh(repos, upgraded, label="Upgraded", color="#55a868")
ax.barh(repos, added, left=upgraded, label="Added", color="#4c72b0")
ax.barh(repos, removed, left=upgraded + added, label="Removed", color="#c44e52")
ax.barh(repos, downgraded, left=upgraded + added + removed, label="Downgraded", color="#ccb974")

ax.set_xlabel("Dependency Count", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Dependency Modifications Breakdown by Repository (Sorted A-Z)", fontweight="bold")
ax.legend(loc="upper right", frameon=True)

totals = upgraded + added + removed + downgraded
for repo, total in zip(repos, totals):
    if total > 0:
        ax.text(
            total + (totals.max() * 0.01 if totals.max() > 0 else 1),
            repo,
            f"{int(total)}",
            va="center",
            ha="left",
            fontsize=8,
            fontweight="bold",
        )

ax.set_xlim(0, (totals.max() * 1.2) if totals.max() > 0 else 10)

# Safe Statistical Text Box (Bottom-Left Zone)
mean_total_deps = totals.mean()
median_total_deps = totals.median()
stats_text_1 = f"Mean Total: {mean_total_deps:.1f}\nMedian Total: {median_total_deps:.1f}"
ax.text(
    0.02, 0.05, stats_text_1,
    transform=ax.transAxes,
    fontsize=9,
    verticalalignment='bottom',
    horizontalalignment='left',
    bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#ccc')
)

plt.tight_layout()
plt.savefig("graphs/rq1_repo_dependency_breakdown.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 2: Module Equivalence Breakdown (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, fig_height))

equiv = df_rq1["equivalent_modules"]
non_equiv = df_rq1["non_equivalent_modules"]

ax.barh(repos, equiv, label="Equivalent Modules", color="#2ecc71")
ax.barh(repos, non_equiv, left=equiv, label="Non-Equivalent Modules", color="#e74c3c")

ax.set_xlabel("Module Count", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Module Equivalence Breakdown by Repository (Sorted A-Z)", fontweight="bold")
ax.legend(loc="upper right", frameon=True)

module_totals = equiv + non_equiv
for repo, total in zip(repos, module_totals):
    if total > 0:
        ax.text(
            total + (module_totals.max() * 0.01 if module_totals.max() > 0 else 1),
            repo,
            f"{int(total)}",
            va="center",
            ha="left",
            fontsize=8,
            fontweight="bold",
        )

ax.set_xlim(0, (module_totals.max() * 1.2) if module_totals.max() > 0 else 10)

# Safe Statistical Text Box (Bottom-Left Zone)
df_rq1["eq_rate_calc"] = np.where(module_totals > 0, (equiv / module_totals) * 100, 0.0)
mean_eq_rate = df_rq1["eq_rate_calc"].mean()
stats_text_2 = f"Mean Equivalence Rate: {mean_eq_rate:.1f}%"
ax.text(
    0.02, 0.05, stats_text_2,
    transform=ax.transAxes,
    fontsize=9,
    verticalalignment='bottom',
    horizontalalignment='left',
    bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#ccc')
)

plt.tight_layout()
plt.savefig("graphs/rq1_repo_module_equivalence.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 3: Combined Test Pass Rate Comparison (Base vs. RQ1)
# -------------------------------------------------------------------
if os.path.exists(base_csv_path):
    df_base = pd.read_csv(base_csv_path)[["repo", "pass_rate"]].rename(columns={"pass_rate": "base_pass_rate"})
    df_base["base_pass_rate"] = pd.to_numeric(
        df_base["base_pass_rate"].astype(str).str.replace(r"\.$", "", regex=True), errors="coerce"
    ).fillna(0.0)
    
    df_combined = pd.merge(df_base, df_rq1[["repo", "pass_rate"]].rename(columns={"pass_rate": "rq1_pass_rate"}), on="repo", how="outer").fillna(0.0)
    df_combined = df_combined.sort_values(by="repo", ascending=False).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10, max(6, len(df_combined) * 0.45)))

    c_repos = df_combined["repo"]
    base_rates = df_combined["base_pass_rate"]
    rq1_rates = df_combined["rq1_pass_rate"]

    y = np.arange(len(c_repos))
    height = 0.38

    rects1 = ax.barh(y - height / 2, base_rates, height, label="Base Pass Rate", color="#e74c3c")
    rects2 = ax.barh(y + height / 2, rq1_rates, height, label="RQ1 Pass Rate", color="#2ecc71")

    ax.set_yticks(y)
    ax.set_yticklabels(c_repos, fontweight="bold")
    ax.set_xlabel("Pass Rate (%)", fontweight="bold")
    ax.set_ylabel("Repositories", fontweight="bold")
    ax.set_title("Test Pass Rate Comparison by Repository (Base vs. RQ1)", fontweight="bold")
    ax.set_xlim(0, 135)  # Expanded X-limit for labels and stats box

    # Calculate statistics for RQ1 pass rates
    mean_rq1 = rq1_rates.mean()
    median_rq1 = rq1_rates.median()
    std_rq1 = rq1_rates.std()
    iqr_rq1 = rq1_rates.quantile(0.75) - rq1_rates.quantile(0.25)

    # Restored Mean and Median Dotted/Dashed Indicator Lines
    ax.axvline(mean_rq1, color='#27ae60', linestyle='--', linewidth=1.5, label=f'RQ1 Mean: {mean_rq1:.1f}%')
    ax.axvline(median_rq1, color='#1e8449', linestyle=':', linewidth=1.5, label=f'RQ1 Median: {median_rq1:.1f}%')

    ax.legend(loc="upper right", frameon=True)

    # Add exact percentages to the right of bars
    for rect in rects1:
        w = rect.get_width()
        if w > 0:
            ax.text(w + 1.5, rect.get_y() + rect.get_height() / 2.0, f"{w:.1f}%", ha="left", va="center", fontsize=7, fontweight="bold")
    for rect in rects2:
        w = rect.get_width()
        if w > 0:
            ax.text(w + 1.5, rect.get_y() + rect.get_height() / 2.0, f"{w:.1f}%", ha="left", va="center", fontsize=7, fontweight="bold")

    # Comprehensive Statistical Summary Box (Std, IQR included)
    stats_text_3 = (
        f"RQ1 Pass Rate Statistics:\n"
        f"• Mean ± Std: {mean_rq1:.1f}% ± {std_rq1:.1f}\n"
        f"• Median [IQR]: {median_rq1:.1f}% [{iqr_rq1:.1f}]\n"
        f"• Base Mean: {base_rates.mean():.1f}%"
    )
    ax.text(
        0.02, 0.05, stats_text_3,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment='bottom',
        horizontalalignment='left',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#ccc')
    )

    plt.tight_layout()
    plt.savefig("graphs/combined_repo_pass_rate.png", dpi=300)
    plt.close()

print("All graphs successfully updated: Sorted A-Z, combined pass rates with mean/median lines, full stats box, and clean layout spacing!")