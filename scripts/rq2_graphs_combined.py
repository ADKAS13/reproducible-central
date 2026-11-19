#!/usr/bin/env python3
"""
rq2_graphs_combined.py — RQ2 (plugin) vs Base ranges, side by side, for five charts.

Lives next to rq2_graphs.py and reuses its loaders, so rq2_graphs.py needs no changes
(the mode / flag columns are added here, after load_flag returns).

    python3 scripts/rq2_graphs_combined.py
    python3 scripts/rq2_graphs_combined.py --root ~/reproducible-central --exclude zeebe-hazelcast-exporter

Writes graphs/combined/combined_*.png:
    combined_flag_action_comparison.png        average dependency changes per module (one axes; RQ2 solid, Base hatched)
    combined_jump_intensity_by_flag.png        versions jumped per upgraded dependency (bars per flag, one colour per mode)
    combined_stale_dependencies_breakdown.png  stale deps before (faded) vs after (solid), one axes
    combined_technical_lag_days_comparison.png avg technical lag before/after, both modes
    combined_volume_vs_magnitude_comparison.png upgraded / jumped / ratio, one axes (ratio on the right axis)

Like the originals, only repositories whose build succeeded are included, and the jump / lag charts need
the collector's --lag columns (they are skipped, with a message, when those are missing).
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rq2_graphs as g                                  # noqa: E402

sns.set_theme(style="whitegrid")

FLAGS = g.FLAGS
ACTIONS = g.ACTIONS
MODES = ["rq2", "base_range"]
MODE_LABEL = {"rq2": "RQ2 (plugin)", "base_range": "Base ranges"}
MODE_COLOR = {"rq2": "#2a6f97", "base_range": "#e07a5f"}
TYPE_COLOR = dict(zip(["Major", "Minor", "Patch"], sns.color_palette("muted", 3)))


def fade(color, amount=0.55):
    """Blend a colour towards white (used for 'before' bars)."""
    r = np.array(to_rgb(color))
    return tuple(r + (1 - r) * amount)


# ------------------------------------------------------------------------------ loading

def load_both(root, exclude):
    tidy_parts, mod_parts = [], []
    for mode in MODES:
        for flag in FLAGS:
            df, mods = g.load_flag(root, mode, flag)
            if df is None or df.empty:
                continue
            df = df.copy()
            df["mode"] = mode
            tidy_parts.append(df)
            if mods is not None:
                mods = mods.copy()
                mods["mode"] = mode
                mods["flag"] = flag
                mod_parts.append(mods)
    if not tidy_parts:
        return None, None
    tidy = pd.concat(tidy_parts, ignore_index=True)
    tidy = tidy[~tidy["repo"].isin(exclude)]
    tidy["built"] = tidy["built"].astype(bool)
    mods = pd.concat(mod_parts, ignore_index=True) if mod_parts else None
    if mods is not None:
        mods = mods[~mods["repo"].isin(exclude)]
    return tidy, mods


def present_modes(df):
    return [m for m in MODES if m in set(df["mode"])]


def has_cols(tidy, cols):
    return all(c in tidy.columns and tidy[c].notna().any() for c in cols)


def built_counts(tidy):
    return tidy[tidy["built"]].groupby(["mode", "flag"])["repo"].nunique()


# ------------------------------------------------------------------------------ charts

# ------------------------------------------------------------------------------ drawing helpers
# One visual language for every combined chart: RQ2 = solid bars, Base ranges = hatched bars (same colour).

plt.rcParams["hatch.linewidth"] = 1.2


def mode_bar(ax, x, value, width, color, mode, fade_it=False):
    face = fade(color) if fade_it else color
    if mode == "base_range":
        return ax.bar(x, value, width, color=face, edgecolor="white", hatch="//", linewidth=0.0)
    return ax.bar(x, value, width, color=face, edgecolor=color if fade_it else face, linewidth=0.8)


def mode_legend_handles():
    return [Patch(facecolor="#777777", edgecolor="#777777", label=MODE_LABEL["rq2"]),
            Patch(facecolor="#777777", edgecolor="white", hatch="//", label=MODE_LABEL["base_range"])]


def n_label(counts, flag):
    return (f"{flag.capitalize()}\n(RQ2 n={int(counts.get(('rq2', flag), 0))}, "
            f"Base n={int(counts.get(('base_range', flag), 0))})")


def c_action_averages(tidy, mods, out):
    if mods is None:
        return
    key = tidy.loc[tidy["built"], ["mode", "flag", "repo"]].drop_duplicates()
    m = mods.merge(key, on=["mode", "flag", "repo"])
    m = m[m["modules"] > 0]
    if m.empty:
        return

    present_cols = [a for a in ACTIONS if a in m.columns]
    if not present_cols:
        return

    avg = m.groupby(["mode", "flag"])[present_cols].mean()

    # Filter to only actions that have non-zero variance/values
    active_actions = [
        a for a in present_cols
        if not avg[a].isna().all() and (avg[a].fillna(0).abs() > 1e-9).any()
    ]
    if not active_actions:
        active_actions = present_cols

    counts = built_counts(tidy)
    colors = dict(zip(ACTIONS, sns.color_palette("muted", len(ACTIONS))))

    n_modes = len(MODES)
    n_slots = len(active_actions) * n_modes  # Now correctly uses active_actions length!
    
    # Tighter width and smaller gap to bunch the clusters closer together
    w = 0.075
    gap = w * 0.2
    step = w + gap
    center = (n_slots - 1) / 2.0

    fig, ax = plt.subplots(figsize=(12, 5))
    for fi, flag in enumerate(FLAGS):
        for ai, action in enumerate(active_actions):
            for mi, mode in enumerate(MODES):
                if (mode, flag) not in avg.index:
                    continue
                v = avg.loc[(mode, flag), action]
                if pd.isna(v):
                    continue
                slot = ai * n_modes + mi
                x_pos = fi + (slot - center) * step
                bar = mode_bar(ax, x_pos, v, w, colors[action], mode)
                ax.bar_label(bar, fmt="%.1f", padding=2, fontsize=10, rotation=0)

    ax.set_xticks(range(len(FLAGS)))
    ax.set_xticklabels([n_label(counts, f) for f in FLAGS])
    ax.set_xlabel("Update flag", fontweight="bold")
    ax.set_ylabel("Average per module", fontweight="bold")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
    ax.set_title(
        "Average Dependency Changes per Module: RQ2 vs Base ranges (built repositories only)",
        fontweight="bold",
        pad=15,
    )
    handles = [
        Patch(facecolor=colors[a], label=a.replace("_", " ").capitalize())
        for a in active_actions
    ]
    ax.legend(
        handles=handles + mode_legend_handles(),
        title="Change / mode",
        loc="upper right",
    )
    g.save(fig, out, "combined_flag_action_comparison.png")


def c_jump_intensity(tidy, out):
    if not has_cols(tidy, ["versions_jumped"]) or tidy["versions_jumped"].fillna(0).sum() == 0:
        print("   skipped combined_jump_intensity_by_flag.png (no versions_jumped; run the collector with --lag)")
        return
    sub = tidy[tidy["built"]].groupby(["mode", "flag"])[["versions_jumped", "upgraded"]].sum().reset_index()
    if sub.empty:
        return
    sub["intensity"] = np.where(sub["upgraded"] > 0, sub["versions_jumped"] / sub["upgraded"], 0.0)
    sub["Mode"] = sub["mode"].map(MODE_LABEL)

    fig, ax = plt.subplots(figsize=(8.5, 5))
    sns.barplot(data=sub, x="flag", y="intensity", hue="Mode", order=FLAGS,
                hue_order=[MODE_LABEL[m] for m in present_modes(sub)],
                palette={MODE_LABEL[m]: MODE_COLOR[m] for m in MODES}, ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.2f", padding=3, fontsize=10)
    ax.set_xticks(range(len(FLAGS)))
    ax.set_xticklabels([f.capitalize() for f in FLAGS])
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Avg Versions Jumped per Upgraded Dependency", fontweight="bold")
    ax.set_title("Upgrade Intensity: RQ2 vs Base ranges", fontweight="bold", pad=15)
    ax.legend(title="")
    g.save(fig, out, "combined_jump_intensity_by_flag.png")


def c_stale_breakdown(tidy, out):
    cols = [f"stale_{k}_{p}" for p in ("before", "after") for k in ("major", "minor", "patch")]
    if not has_cols(tidy, cols):
        print("   skipped combined_stale_dependencies_breakdown.png (no stale_* columns; run the collector with --lag)")
        return
    sub = tidy[tidy["built"]].groupby(["mode", "flag"])[cols].sum(min_count=1)
    counts = built_counts(tidy)
    kinds = ["Major", "Minor", "Patch"]
    w = 0.065

    fig, ax = plt.subplots(figsize=(15, 6))
    for fi, flag in enumerate(FLAGS):
        for ki, kind in enumerate(kinds):
            for pi, phase in enumerate(("before", "after")):
                for mi, mode in enumerate(MODES):
                    if (mode, flag) not in sub.index:
                        continue
                    v = sub.loc[(mode, flag), f"stale_{kind.lower()}_{phase}"]
                    if pd.isna(v):
                        continue
                    slot = ki * 4 + pi * 2 + mi          # per type: RQ2 before, Base before, RQ2 after, Base after
                    bar = mode_bar(ax, fi + (slot - 5.5) * w, v, w, TYPE_COLOR[kind], mode, fade_it=(phase == "before"))
                    ax.bar_label(bar, fmt="%d", padding=2, fontsize=15, rotation=90)
    ax.set_xticks(range(len(FLAGS)))
    ax.set_xticklabels([n_label(counts, f) for f in FLAGS])
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Total Stale Dependencies", fontweight="bold")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)       # headroom for the rotated value labels
    ax.set_title("Stale Dependencies Before vs After: RQ2 vs Base ranges (built repositories only)",
                 fontweight="bold", pad=15)
    handles = [Patch(facecolor=c, label=k) for k, c in TYPE_COLOR.items()]
    handles += [Patch(facecolor=fade("#555555"), edgecolor="#555555", label="Before update (faded)"),
                Patch(facecolor="#555555", label="After update (solid)")]
    ax.legend(handles=handles + mode_legend_handles(), title="Stale type / state / mode", loc="upper left")
    g.save(fig, out, "combined_stale_dependencies_breakdown.png")


def c_lag_days(tidy, out):
    if not has_cols(tidy, ["lag_days_before", "lag_days_after"]):
        print("   skipped combined_technical_lag_days_comparison.png (no lag_days columns; run the collector with --lag)")
        return
    sub = tidy[tidy["built"]].groupby(["mode", "flag"])[["lag_days_before", "lag_days_after"]].mean().reset_index()
    if sub.empty:
        return
    rows, palette, order = [], {}, []
    for mode in present_modes(sub):
        for phase, col in (("before", "lag_days_before"), ("after", "lag_days_after")):
            name = f"{MODE_LABEL[mode]} — {phase}"
            order.append(name)
            palette[name] = fade(MODE_COLOR[mode]) if phase == "before" else MODE_COLOR[mode]
            for _, r in sub[sub["mode"] == mode].iterrows():
                rows.append(dict(flag=r["flag"], Series=name, days=r[col]))
    d = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    sns.barplot(data=d, x="flag", y="days", hue="Series", order=FLAGS, hue_order=order, palette=palette, ax=ax)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.0f", padding=3, fontsize=10)
    ax.set_xticks(range(len(FLAGS)))
    ax.set_xticklabels([f.capitalize() for f in FLAGS])
    ax.set_xlabel("Update Flag", fontweight="bold")
    ax.set_ylabel("Average Technical Lag (Days)", fontweight="bold")
    ax.set_title("Technical Lag Before vs After Upgrading: RQ2 vs Base ranges", fontweight="bold", pad=15)
    ax.legend(title="", loc="upper left", bbox_to_anchor=(1.02, 1.0))
    g.save(fig, out, "combined_technical_lag_days_comparison.png")


def c_volume_vs_magnitude(tidy, out):
    if not has_cols(tidy, ["versions_jumped"]) or tidy["versions_jumped"].fillna(0).sum() == 0:
        print("   skipped combined_volume_vs_magnitude_comparison.png (no versions_jumped; run the collector with --lag)")
        return
    sub = tidy[tidy["built"]].groupby(["mode", "flag"])[["upgraded", "versions_jumped"]].sum()
    sub["ratio"] = np.where(sub["upgraded"] > 0, sub["versions_jumped"] / sub["upgraded"], 0.0)
    counts = built_counts(tidy)
    c_up, c_jump, c_ratio = "#4c72b0", "#dd8452", "#55a868"
    w = 0.12

    fig, ax1 = plt.subplots(figsize=(11, 6))
    ax2 = ax1.twinx()
    for fi, flag in enumerate(FLAGS):
        for mi, mode in enumerate(MODES):
            if (mode, flag) not in sub.index:
                continue
            r = sub.loc[(mode, flag)]
            b1 = mode_bar(ax1, fi + (0 * 2 + mi - 2.5) * w, r["upgraded"], w, c_up, mode)
            b2 = mode_bar(ax1, fi + (1 * 2 + mi - 2.5) * w, r["versions_jumped"], w, c_jump, mode)
            b3 = mode_bar(ax2, fi + (2 * 2 + mi - 2.5) * w, r["ratio"], w, c_ratio, mode)
            ax1.bar_label(b1, fmt="%d", padding=2, fontsize=10)
            ax1.bar_label(b2, fmt="%d", padding=2, fontsize=10)
            ax2.bar_label(b3, fmt="%.2f", padding=2, fontsize=10)
    ax1.set_xticks(range(len(FLAGS)))
    ax1.set_xticklabels([n_label(counts, f) for f in FLAGS])
    ax1.set_xlabel("Update Flag", fontweight="bold")
    ax1.set_ylabel("Cumulative count (upgraded & jumped)", fontweight="bold")
    ax2.set_ylabel("Versions jumped per upgraded dependency", fontweight="bold", color=c_ratio)
    ax2.tick_params(axis="y", labelcolor=c_ratio)
    ax2.grid(False)
    ax1.set_ylim(0, ax1.get_ylim()[1] * 1.08)
    ax2.set_ylim(0, ax2.get_ylim()[1] * 1.08)
    handles = [Patch(facecolor=c_up, label="Upgraded dependencies"),
               Patch(facecolor=c_jump, label="Total versions jumped"),
               Patch(facecolor=c_ratio, label="Jump ratio (jumped / upgraded, right axis)")]
    fig.legend(handles=handles + mode_legend_handles(), loc="lower center", ncol=5, frameon=True,
               bbox_to_anchor=(0.5, -0.06))
    ax1.set_title("Volume, Magnitude and Jump Intensity per Update Flag: RQ2 vs Base ranges (built repositories only)",
                  fontweight="bold", pad=15)
    g.save(fig, out, "combined_volume_vs_magnitude_comparison.png")


# ------------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."), help="reproducible-central root")
    ap.add_argument("--out", type=Path, default=None, help="output directory (default graphs/combined)")
    ap.add_argument("--exclude", nargs="*", default=[], help="repositories to leave out")
    a = ap.parse_args()
    root = a.root.resolve()
    out = a.out or (root / "graphs" / "combined")
    out.mkdir(parents=True, exist_ok=True)

    tidy, mods = load_both(root, a.exclude)
    if tidy is None:
        print("No results found for either mode; have the collectors been run?")
        return

    print("\nBuilt repositories used (mode, flag):")
    counts = built_counts(tidy)
    for mode in present_modes(tidy):
        print("  " + MODE_LABEL[mode].ljust(14) + "  ".join(f"{f}: {int(counts.get((mode, f), 0))}" for f in FLAGS))
    print()

    c_action_averages(tidy, mods, out)
    c_jump_intensity(tidy, out)
    c_stale_breakdown(tidy, out)
    c_lag_days(tidy, out)
    c_volume_vs_magnitude(tidy, out)
    print(f"Combined graphs written to {out}")


if __name__ == "__main__":
    main()