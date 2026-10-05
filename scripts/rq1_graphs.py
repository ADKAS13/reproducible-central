import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Load data directly from your repository CSV file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join("results", "rq1_results.csv")
df_repo = pd.read_csv(csv_path)

sns.set_theme(style="whitegrid")

# Ensure output directory exists
os.makedirs("graphs", exist_ok=True)

# -------------------------------------------------------------------
# Graph 1: Stacked Dependency Actions Breakdown (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))

repos = df_repo["repo"]
upgraded = df_repo["upgraded_count"]
added = df_repo["added_count"]
removed = df_repo["removed_count"]
downgraded = df_repo["downgraded_count"]

# Horizontal Stacked Bars
ax.barh(repos, upgraded, label="Upgraded", color="#55a868")
ax.barh(repos, added, left=upgraded, label="Added", color="#4c72b0")
ax.barh(
    repos,
    removed,
    left=upgraded + added,
    label="Removed",
    color="#c44e52",
)
ax.barh(
    repos,
    downgraded,
    left=upgraded + added + removed,
    label="Downgraded",
    color="#ccb974",
)

ax.set_xlabel("Dependency Count", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title(
    "Dependency Modifications Breakdown by Repository", fontweight="bold"
)
ax.legend(loc="lower right")

# Annotate total counts at the end of each stacked bar
totals = upgraded + added + removed + downgraded
for repo, total in zip(repos, totals):
    if total > 0:
        ax.text(
            total + (totals.max() * 0.01),
            repo,
            f"{int(total)}",
            va="center",
            ha="left",
            fontweight="bold",
        )

# Add spacing on the x-axis for count labels
ax.set_xlim(0, totals.max() * 1.1)

plt.tight_layout()
plt.savefig("graphs/rq1_repo_dependency_breakdown.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 2: Module Equivalence Breakdown (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))

equiv = df_repo["equivalent_modules"]
non_equiv = df_repo["non_equivalent_modules"]

ax.barh(repos, equiv, label="Equivalent Modules", color="#2ecc71")
ax.barh(
    repos,
    non_equiv,
    left=equiv,
    label="Non-Equivalent Modules",
    color="#e74c3c",
)

ax.set_xlabel("Module Count", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Module Equivalence Breakdown by Repository", fontweight="bold")
ax.legend(loc="lower right")

# Annotate total module counts at the end of each stacked bar
module_totals = equiv + non_equiv
for repo, total in zip(repos, module_totals):
    if total > 0:
        ax.text(
            total + (module_totals.max() * 0.01),
            repo,
            f"{int(total)}",
            va="center",
            ha="left",
            fontweight="bold",
        )

ax.set_xlim(0, module_totals.max() * 1.1)

plt.tight_layout()
plt.savefig("graphs/rq1_repo_module_equivalence.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 3: Pass / Success Rate per Repository (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))

bars = ax.barh(repos, df_repo["pass_rate"], color="#2ecc71", height=0.45)

ax.set_xlabel("Pass Rate (%)", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Test Pass Rate by Repository", fontweight="bold")
ax.set_xlim(0, 115)  # Leave room for percentage labels on the right

# Add exact percentages to the right of each horizontal bar
for bar in bars:
    width = bar.get_width()
    ax.text(
        width + 1.5,
        bar.get_y() + bar.get_height() / 2.0,
        f"{width:.1f}%",
        ha="left",
        va="center",
        fontweight="bold",
    )

plt.tight_layout()
plt.savefig("graphs/rq1_repo_pass_rate.png", dpi=300)
plt.close()