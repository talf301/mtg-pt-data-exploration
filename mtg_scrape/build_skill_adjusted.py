"""Compute per-archetype observed vs Elo-expected win rates for PT Strixhaven.

mtgeloproject's Elo scale, per their FAQ:
  - Players enter at 1500.
  - 200-point gap -> 60% expected win rate.
This implies P(A wins) = 1 / (1 + 1.5 ** ((R_B - R_A) / 200)).
"""
from __future__ import annotations

import pandas as pd

ELO_BASE = 1.5      # base of the Elo exponent
ELO_SCALE = 200.0   # rating gap that corresponds to 60% win rate


def _elo_expected(my_elo: float, opp_elo: float) -> float:
    """Elo-expected win probability for a player at my_elo vs opp_elo."""
    return 1.0 / (1.0 + ELO_BASE ** ((opp_elo - my_elo) / ELO_SCALE))


_FLIP = {"W": "L", "L": "W"}


def to_skill_long_frame(matchups: pd.DataFrame) -> pd.DataFrame:
    """Expand each decided non-mirror match into two long-frame rows.

    Columns: my_arch, opp_arch, my_elo, opp_elo, result.

    Filters out:
      - draws (result == "D")
      - mirror matches (archetype_a == archetype_b)
      - rows missing either elo_a_pre or elo_b_pre
    """
    keep = (
        matchups["result"].isin(_FLIP)
        & (matchups["archetype_a"] != matchups["archetype_b"])
        & matchups["elo_a_pre"].notna()
        & matchups["elo_b_pre"].notna()
    )
    m = matchups[keep]

    forward = pd.DataFrame({
        "my_arch":  m["archetype_a"].to_numpy(),
        "opp_arch": m["archetype_b"].to_numpy(),
        "my_elo":   m["elo_a_pre"].to_numpy(dtype=float),
        "opp_elo":  m["elo_b_pre"].to_numpy(dtype=float),
        "result":   m["result"].to_numpy(),
    })
    mirror = pd.DataFrame({
        "my_arch":  m["archetype_b"].to_numpy(),
        "opp_arch": m["archetype_a"].to_numpy(),
        "my_elo":   m["elo_b_pre"].to_numpy(dtype=float),
        "opp_elo":  m["elo_a_pre"].to_numpy(dtype=float),
        "result":   m["result"].map(_FLIP).to_numpy(),
    })
    return pd.concat([forward, mirror], ignore_index=True)


def compute_archetype_summary(long: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the long-frame into one row per archetype.

    Output columns:
      archetype, games, observed_wins, observed_losses, observed_wr,
      expected_wins, expected_losses, expected_wr, residual
    """
    if long.empty:
        return pd.DataFrame(columns=[
            "archetype", "games",
            "observed_wins", "observed_losses", "observed_wr",
            "expected_wins", "expected_losses", "expected_wr",
            "residual",
        ])

    work = long.copy()
    work["p_win"] = work.apply(
        lambda r: _elo_expected(r["my_elo"], r["opp_elo"]),
        axis=1,
    )
    work["obs_w"] = (work["result"] == "W").astype(int)
    work["obs_l"] = (work["result"] == "L").astype(int)
    work["exp_w"] = work["p_win"]
    work["exp_l"] = 1.0 - work["p_win"]

    grouped = work.groupby("my_arch").agg(
        games=("result", "size"),
        observed_wins=("obs_w", "sum"),
        observed_losses=("obs_l", "sum"),
        expected_wins=("exp_w", "sum"),
        expected_losses=("exp_l", "sum"),
    ).reset_index().rename(columns={"my_arch": "archetype"})

    grouped["observed_wr"] = grouped["observed_wins"] / grouped["games"]
    grouped["expected_wr"] = grouped["expected_wins"] / grouped["games"]
    grouped["residual"] = grouped["observed_wr"] - grouped["expected_wr"]

    return grouped[[
        "archetype", "games",
        "observed_wins", "observed_losses", "observed_wr",
        "expected_wins", "expected_losses", "expected_wr",
        "residual",
    ]]


from pathlib import Path


def render_csv(summary: pd.DataFrame, out_path: Path) -> None:
    """Write the summary DataFrame to CSV, sorted by residual descending."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary.sort_values("residual", ascending=False).to_csv(out_path, index=False)


import matplotlib

matplotlib.use("Agg")  # no GUI
import matplotlib.pyplot as plt


def render_png(
    summary: pd.DataFrame,
    archetypes: list[str],
    out_path: Path,
) -> None:
    """Paired horizontal bars (expected, observed) per archetype, sorted by residual desc.

    Only renders archetypes in the provided list (typically top-10 + Other).
    Reference line at 50%. Residual annotated at the right end of each pair.
    Y-tick label shows archetype name with sample size: 'Izzet Prowess (n=719)'.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    subset = summary[summary["archetype"].isin(archetypes)].copy()
    subset = subset[subset["games"] > 0]  # skip empties
    subset = subset.sort_values("residual", ascending=False).reset_index(drop=True)

    n = len(subset)
    if n == 0:
        # Defensive: empty plot
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(10, max(4, 0.6 * n + 1)))

    bar_h = 0.35
    y = list(range(n))
    expected = subset["expected_wr"].to_numpy()
    observed = subset["observed_wr"].to_numpy()
    residual = subset["residual"].to_numpy()

    # Top bars: expected (lighter); bottom bars: observed (darker)
    ax.barh([yi + bar_h / 2 for yi in y], expected, height=bar_h,
            color="#a5b4d1", label="Expected (Elo)")
    ax.barh([yi - bar_h / 2 for yi in y], observed, height=bar_h,
            color="#3b5998", label="Observed")

    # Reference line at 50%
    ax.axvline(0.5, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)

    # Residual annotation at the right end of each archetype
    x_text = max(expected.max(), observed.max()) + 0.03
    for yi, r in zip(y, residual):
        sign = "+" if r >= 0 else ""
        color = "#1a7a1a" if r >= 0 else "#a01515"
        ax.text(x_text, yi, f"{sign}{r * 100:.1f}%", va="center", color=color, fontsize=9, weight="bold")

    # Y-axis labels: "archetype (n=games)"
    labels = [f"{row.archetype} (n={int(row.games)})" for row in subset.itertuples()]
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # highest residual at top

    ax.set_xlim(0, x_text + 0.08)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Win rate")
    ax.set_title("PT Secrets of Strixhaven — observed vs Elo-expected win rate")
    ax.legend(loc="lower right", framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
