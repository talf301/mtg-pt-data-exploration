"""Compute the PT Strixhaven archetype matchup matrix and render CSVs + PNG."""
from __future__ import annotations

import pandas as pd

OTHER_LABEL = "Other"


def top_n_archetypes(matchups: pd.DataFrame, n: int = 10) -> list[str]:
    """Return the n most-played archetypes, by total appearances across both sides.

    Ties broken alphabetically.
    """
    counts = pd.concat([matchups["archetype_a"], matchups["archetype_b"]]).value_counts()
    ordered = (
        counts.rename_axis("archetype")
        .reset_index(name="count")
        .sort_values(by=["count", "archetype"], ascending=[False, True])
    )
    return ordered.head(n)["archetype"].tolist()


def map_to_bucket(top_n: list[str], other_label: str = OTHER_LABEL):
    """Return a callable: archetype -> archetype if in top_n else other_label."""
    top_set = set(top_n)

    def _bucket(archetype: str) -> str:
        return archetype if archetype in top_set else other_label

    return _bucket


_FLIP = {"W": "L", "L": "W"}


def to_long_frame(
    matchups: pd.DataFrame,
    top_n: list[str],
    other_label: str = OTHER_LABEL,
) -> pd.DataFrame:
    """Expand each matchups row into two long-frame rows (one per perspective).

    - Drops draws (result == "D").
    - Maps non-top-N archetypes to other_label.
    - Output columns: my_arch, opp_arch, result.
    """
    bucket = map_to_bucket(top_n, other_label=other_label)
    decided = matchups[matchups["result"].isin(_FLIP)].copy()

    forward = pd.DataFrame({
        "my_arch": decided["archetype_a"].map(bucket),
        "opp_arch": decided["archetype_b"].map(bucket),
        "result": decided["result"],
    })
    mirror = pd.DataFrame({
        "my_arch": decided["archetype_b"].map(bucket),
        "opp_arch": decided["archetype_a"].map(bucket),
        "result": decided["result"].map(_FLIP),
    })
    return pd.concat([forward, mirror], ignore_index=True)


def compute_matrix(
    long: pd.DataFrame,
    ordered_labels: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute square wins and losses DataFrames indexed by (my_arch, opp_arch).

    Returns two DataFrames with rows=cols=ordered_labels (filling 0 where no data exists).
    """
    decided = long[long["result"].isin(("W", "L"))]
    wins_pivot = (
        decided[decided["result"] == "W"]
        .groupby(["my_arch", "opp_arch"]).size()
        .unstack(fill_value=0)
    )
    losses_pivot = (
        decided[decided["result"] == "L"]
        .groupby(["my_arch", "opp_arch"]).size()
        .unstack(fill_value=0)
    )
    wins = wins_pivot.reindex(index=ordered_labels, columns=ordered_labels, fill_value=0)
    losses = losses_pivot.reindex(index=ordered_labels, columns=ordered_labels, fill_value=0)
    return wins.astype(int), losses.astype(int)


def compute_win_rate(wins: pd.DataFrame, losses: pd.DataFrame) -> pd.DataFrame:
    """Compute the win rate matrix; suppress the diagonal to NaN."""
    total = wins + losses
    wr = wins.where(total > 0).astype(float).div(total.where(total > 0))
    for label in wr.index:
        if label in wr.columns:
            wr.loc[label, label] = float("nan")
    return wr
