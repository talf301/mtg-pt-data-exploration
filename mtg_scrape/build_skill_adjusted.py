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
