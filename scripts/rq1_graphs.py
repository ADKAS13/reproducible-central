import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import os

# Load data directly from your repository CSV file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join("results", "rq1_results.csv")
df_repo = pd.read_csv(csv_path)

sns.set_theme(style="whitegrid")

# -------------------------------------------------------------------
# Graph 1: Stacked Dependency Actions Breakdown (Individual Image)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

repos = df_repo["repo"]
upgraded = df_repo["upgraded_count"]
added = df_repo["added_count"]
removed = df_repo["removed_count"]
downgraded = df_repo["downgraded_count"]

ax.bar(repos, upgraded, label="Upgraded", color="#55a868")
ax.bar(repos, added, bottom=upgraded, label="Added", color="#4c72b0")
ax.bar(
    repos,
    removed,
    bottom=upgraded + added,
    label="Removed",
    color="#c44e52",
)
ax.bar(
    repos,
    downgraded,
    bottom=upgraded + added + removed,
    label="Downgraded",
    color="#ccb974",
)

ax.set_ylabel("Dependency Count", fontweight="bold")
ax.set_xlabel("Repositories", fontweight="bold")
ax.set_title(
    "Dependency Modifications Breakdown by Repository", fontweight="bold"
)
ax.legend(loc="upper left")

plt.tight_layout()
plt.savefig("graphs/repo_dependency_breakdown.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 2: Module Equivalence Breakdown (Individual Image)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

equiv = df_repo["equivalent_modules"]
non_equiv = df_repo["non_equivalent_modules"]

ax.bar(repos, equiv, label="Equivalent Modules", color="#2ecc71")
ax.bar(
    repos,
    non_equiv,
    bottom=equiv,
    label="Non-Equivalent Modules",
    color="#e74c3c",
)

ax.set_ylabel("Module Count", fontweight="bold")
ax.set_xlabel("Repositories", fontweight="bold")
ax.set_title("Module Equivalence Breakdown by Repository", fontweight="bold")
ax.legend(loc="upper left")

plt.tight_layout()
plt.savefig("graphs/repo_module_equivalence.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 3: Pass / Success Rate per Repository (Individual Image)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

bars = ax.bar(repos, df_repo["pass_rate"], color="#2ecc71", width=0.45)

ax.set_ylabel("Pass Rate (%)", fontweight="bold")
ax.set_xlabel("Repositories", fontweight="bold")
ax.set_title("Test Pass Rate by Repository", fontweight="bold")
ax.set_ylim(0, 110)

# Add exact percentages over bars
for bar in bars:
  height = bar.get_height()
  ax.text(
      bar.get_x() + bar.get_width() / 2.0,
      height + 1.5,
      f"{height:.1f}%",
      ha="center",
      va="bottom",
      fontweight="bold",
  )

plt.tight_layout()
plt.savefig("graphs/repo_pass_rate.png", dpi=300)
plt.close()