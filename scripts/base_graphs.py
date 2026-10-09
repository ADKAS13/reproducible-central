import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Load data directly from base results CSV file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join("results", "base_results.csv")
df_repo = pd.read_csv(csv_path)

sns.set_theme(style="whitegrid")

# Ensure output directory exists
os.makedirs("graphs", exist_ok=True)

# Preprocessing: Fill missing values if any
df_repo["pass_rate"] = df_repo["pass_rate"].fillna(0)

# -------------------------------------------------------------------
# Graph 1: Test Pass Rate by Repository (Horizontal)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))

repos = df_repo["repo"]
pass_rates = df_repo["pass_rate"]

bars = ax.barh(repos, pass_rates, color="#2ecc71")

ax.set_xlabel("Pass Rate (%)", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Test Pass Rate by Repository", fontweight="bold")
ax.set_xlim(0, 115)  # Leave room for percentage labels on the right

# Add exact percentages to the right of each horizontal bar
for bar, pass_rate in zip(bars, pass_rates):
    width = bar.get_width()
    if pd.isna(pass_rate) or width == 0:
        label_text = "N/A"
    else:
        label_text = f"{width:.1f}%"

    ax.text(
        width + 1.5,
        bar.get_y() + bar.get_height() / 2.0,
        label_text,
        ha="left",
        va="center",
        fontweight="bold",
    )

plt.tight_layout()
plt.savefig("graphs/base_repo_pass_rate.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 2: Test Execution Breakdown (Horizontal Stacked)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))

passed = df_repo["total_passed"]
failed_errored = df_repo["total_failed"] + df_repo["total_errored"]
skipped = df_repo["total_skipped"]

ax.barh(repos, passed, label="Passed", color="#2ecc71")
ax.barh(
    repos,
    failed_errored,
    left=passed,
    label="Failed / Errored",
    color="#e74c3c",
)
ax.barh(
    repos,
    skipped,
    left=passed + failed_errored,
    label="Skipped",
    color="#f39c12",
)

ax.set_xlabel("Test Count", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Test Execution Breakdown by Repository", fontweight="bold")
ax.legend(loc="lower right")

# Annotate total test counts at the end of each stacked bar
test_totals = passed + failed_errored + skipped
for repo, total in zip(repos, test_totals):
    if total > 0:
        ax.text(
            total + (test_totals.max() * 0.01),
            repo,
            f"{int(total)}",
            va="center",
            ha="left",
            fontweight="bold",
        )

ax.set_xlim(0, test_totals.max() * 1.1)

plt.tight_layout()
plt.savefig("graphs/base_repo_test_breakdown.png", dpi=300)
plt.close()

# -------------------------------------------------------------------
# Graph 3: Build Success Rate Summary (Pie Chart)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(6, 6))

build_counts = df_repo["build_success"].value_counts()
pass_count = build_counts.get(True, 0)
fail_count = build_counts.get(False, 0)

labels = []
sizes = []
colors = []

if pass_count > 0:
    labels.append(f"Pass ({pass_count})")
    sizes.append(pass_count)
    colors.append("#2ecc71")

if fail_count > 0:
    labels.append(f"Fail ({fail_count})")
    sizes.append(fail_count)
    colors.append("#e74c3c")

ax.pie(
    sizes,
    labels=labels,
    autopct="%1.1f%%",
    startangle=90,
    colors=colors,
    textprops={"fontweight": "bold"},
)
ax.set_title("Overall Build Success Rate", fontweight="bold")

plt.tight_layout()
plt.savefig("graphs/base_build_success_rate.png", dpi=300)
plt.close()

print("Graphs successfully saved to graphs/ directory.")