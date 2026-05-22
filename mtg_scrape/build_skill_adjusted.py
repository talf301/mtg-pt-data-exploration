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
