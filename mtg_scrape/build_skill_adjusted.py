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
