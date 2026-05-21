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
