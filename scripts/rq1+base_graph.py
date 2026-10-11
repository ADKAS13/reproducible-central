import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Load data from both repository CSV files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
base_csv_path = os.path.join("results", "base_results.csv")
rq1_csv_path = os.path.join("results", "rq1_results.csv")

df_base = pd.read_csv(base_csv_path)[["repo", "pass_rate"]].rename(columns={"pass_rate": "base_pass_rate"})
df_rq1 = pd.read_csv(rq1_csv_path)[["repo", "pass_rate"]].rename(columns={"pass_rate": "rq1_pass_rate"})

# Merge datasets on repository name
df_merged = pd.merge(df_base, df_rq1, on="repo", how="outer")
df_merged["base_pass_rate"] = df_merged["base_pass_rate"].fillna(0)
df_merged["rq1_pass_rate"] = df_merged["rq1_pass_rate"].fillna(0)

# Sort repositories alphabetically A-Z
df_merged = df_merged.sort_values(by="repo", ascending=True).reset_index(drop=True)

# Apply base theme styling
sns.set_theme(style="whitegrid")

# Ensure output directory exists
os.makedirs("graphs", exist_ok=True)

# -------------------------------------------------------------------
# Combined Graph: Test Pass Rate Comparison (Base vs. RQ1)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, max(6, len(df_merged) * 0.4)))

repos = df_merged["repo"]
base_rates = df_merged["base_pass_rate"]
rq1_rates = df_merged["rq1_pass_rate"]

y = np.arange(len(repos))
height = 0.35

# Grouped horizontal bars
rects1 = ax.barh(y - height / 2, base_rates, height, label="Base Pass Rate", color="#e74c3c")
rects2 = ax.barh(y + height / 2, rq1_rates, height, label="RQ1 Pass Rate", color="#2ecc71")

ax.set_yticks(y)
ax.set_yticklabels(repos, fontweight="bold")
ax.set_xlabel("Pass Rate (%)", fontweight="bold")
ax.set_ylabel("Repositories", fontweight="bold")
ax.set_title("Test Pass Rate Comparison by Repository (Base vs. RQ1)", fontweight="bold")
ax.set_xlim(0, 115)  # Leave room for percentage labels on the right
ax.legend(loc="lower right")

# Add exact percentage labels to the right of each horizontal bar
for rect in rects1:
    width = rect.get_width()
    if width > 0:
        ax.text(
            width + 1.5,
            rect.get_y() + rect.get_height() / 2.0,
            f"{width:.1f}%",
            ha="left",
            va="center",
            fontsize=8,
            fontweight="bold",
        )

for rect in rects2:
    width = rect.get_width()
    if width > 0:
        ax.text(
            width + 1.5,
            rect.get_y() + rect.get_height() / 2.0,
            f"{width:.1f}%",
            ha="left",
            va="center",
            fontsize=8,
            fontweight="bold",
        )

plt.tight_layout()
plt.savefig("graphs/combined_repo_pass_rate.png", dpi=300)
plt.close()

print("Combined pass rate graph successfully saved to graphs/combined_repo_pass_rate.png")