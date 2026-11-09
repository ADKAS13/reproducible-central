import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid")
GRAPHS_DIR = os.path.abspath("graphs")
os.makedirs(GRAPHS_DIR, exist_ok=True)

# Your exact verified data points
data = {
    "flag": ["Major", "Minor", "Patch"],
    "build_success_rate": [85.71, 85.71, 85.71],  # 24/28 repos
    "test_pass_rate": [86.87, 86.78, 87.00],        # Verified test pass rates
    "upgraded_per_module_avg": [13.33871489, 12.2119505, 9.440545977],               # Average upgraded deps per module
    "upgraded_avg": [87.14285714, 76.35714286, 50.96428571]
}

df_macro = pd.DataFrame(data)

fig, ax1 = plt.subplots(figsize=(9, 5))
x_idx = np.arange(len(df_macro))

# Left Y-Axis: Success Rates (%)
line1 = ax1.plot(
    x_idx, df_macro["build_success_rate"], 
    color="#4c72b0", marker="s", linewidth=2.5, markersize=8, label="Build Success Rate (%)"
)
line2 = ax1.plot(
    x_idx, df_macro["test_pass_rate"], 
    color="#55a868", marker="^", linewidth=2.5, markersize=8, label="Test Pass Rate (%)"
)

ax1.set_xlabel("Version Flag Scope", fontweight="bold")
ax1.set_ylabel("Success Rate (%)", fontweight="bold", color="#2b2b2b")
ax1.set_xticks(x_idx)
ax1.set_xticklabels(df_macro["flag"])
ax1.set_ylim(75, 95)  # Zoomed in slightly so the subtle differences between major/minor/patch are visible

# Right Y-Axis: Average Upgraded Dependencies per Module
ax2 = ax1.twinx()
line3 = ax2.plot(
    x_idx, df_macro["upgraded_per_module_avg"], 
    color="#c44e52", marker="o", linewidth=2.5, markersize=8, linestyle="--", label="Avg Upgraded Deps / Module"
)
ax2.set_ylabel("Average Upgraded Dependencies / Module", fontweight="bold", color="#c44e52")
ax2.tick_params(axis="y", labelcolor="#c44e52")
ax2.set_ylim(0, max(df_macro["upgraded_per_module_avg"]) * 1.3)
ax2.grid(False)

# Value annotations directly above/below data points for clarity
for i in range(len(df_macro)):
    ax1.text(i, df_macro["build_success_rate"][i] + 0.5, f"{df_macro['build_success_rate'][i]:.2f}%", color="#4c72b0", fontweight="bold", ha="center")
    ax1.text(i, df_macro["test_pass_rate"][i] - 0.8, f"{df_macro['test_pass_rate'][i]:.2f}%", color="#55a868", fontweight="bold", ha="center")
    ax2.text(i, df_macro["upgraded_per_module_avg"][i] + 0.4, f"{df_macro['upgraded_per_module_avg'][i]:.2f}", color="#c44e52", fontweight="bold", ha="center")

# Consolidated legend placed outside the plot area
lines = line1 + line2 + line3
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc="upper left", bbox_to_anchor=(1.15, 1.0), borderaxespad=0.0)

plt.title("Build/Test Success vs. Upgraded Dependencies/Module by Flag Scope", fontweight="bold", pad=15)
plt.tight_layout()
output_path = os.path.join(GRAPHS_DIR, "rq2_dual_axis_success_vs_upgrades_per_module.png")
plt.savefig(output_path, dpi=300, bbox_inches="tight")
plt.close()

print(f"Successfully generated clean dual-axis graph at: {output_path}")


fig, ax1 = plt.subplots(figsize=(9, 5))
# Left Y-Axis: Success Rates (%)
line1 = ax1.plot(
    x_idx, df_macro["build_success_rate"], 
    color="#4c72b0", marker="s", linewidth=2.5, markersize=8, label="Build Success Rate (%)"
)
line2 = ax1.plot(
    x_idx, df_macro["test_pass_rate"], 
    color="#55a868", marker="^", linewidth=2.5, markersize=8, label="Test Pass Rate (%)"
)

ax1.set_xlabel("Version Flag Scope", fontweight="bold")
ax1.set_ylabel("Success Rate (%)", fontweight="bold", color="#2b2b2b")
ax1.set_xticks(x_idx)
ax1.set_xticklabels(df_macro["flag"])
ax1.set_ylim(75, 95)  # Zoomed in slightly so the subtle differences between major/minor/patch are visible

# Right Y-Axis: Average Upgraded Dependencies per Module
ax2 = ax1.twinx()
line3 = ax2.plot(
    x_idx, df_macro["upgraded_avg"], 
    color="#c44e52", marker="o", linewidth=2.5, markersize=8, linestyle="--", label="Avg Upgraded Deps / Module"
)
ax2.set_ylabel("Average Upgraded Dependencies", fontweight="bold", color="#c44e52")
ax2.tick_params(axis="y", labelcolor="#c44e52")
ax2.set_ylim(0, max(df_macro["upgraded_avg"]) * 1.3)
ax2.grid(False)

# Value annotations directly above/below data points for clarity
for i in range(len(df_macro)):
    ax1.text(i, df_macro["build_success_rate"][i] + 0.5, f"{df_macro['build_success_rate'][i]:.2f}%", color="#4c72b0", fontweight="bold", ha="center")
    ax1.text(i, df_macro["test_pass_rate"][i] - 0.8, f"{df_macro['test_pass_rate'][i]:.2f}%", color="#55a868", fontweight="bold", ha="center")
    ax2.text(i, df_macro["upgraded_avg"][i] + 0.4, f"{df_macro['upgraded_avg'][i]:.2f}", color="#c44e52", fontweight="bold", ha="center")

# Consolidated legend placed outside the plot area
lines = line1 + line2 + line3
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc="upper left", bbox_to_anchor=(1.15, 1.0), borderaxespad=0.0)

plt.title("Build/Test Success vs. Upgraded Dependencies by Flag Scope", fontweight="bold", pad=15)
plt.tight_layout()
output_path = os.path.join(GRAPHS_DIR, "rq2_dual_axis_success_vs_upgrades.png")
plt.savefig(output_path, dpi=300, bbox_inches="tight")
plt.close()

print(f"Successfully generated clean dual-axis graph at: {output_path}")