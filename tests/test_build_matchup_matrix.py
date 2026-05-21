import pandas as pd
import pytest

from mtg_scrape.build_matchup_matrix import top_n_archetypes, map_to_bucket


def _matchups(rows):
    """Build a minimal matchups DataFrame from a list of (arch_a, arch_b, result)."""
    return pd.DataFrame(rows, columns=["archetype_a", "archetype_b", "result"])


def test_top_n_archetypes_ranks_by_total_appearances():
    # IzzetProwess appears 3 times, Mono-Green 2, Rogue 1. Top 2 should be Izzet, Mono-Green.
    m = _matchups([
        ("IzzetProwess",  "Mono-Green", "W"),
        ("IzzetProwess",  "Rogue",      "W"),
        ("Mono-Green",    "IzzetProwess", "L"),
    ])
    assert top_n_archetypes(m, n=2) == ["IzzetProwess", "Mono-Green"]


def test_top_n_archetypes_ties_broken_alphabetically():
    # Both archetypes have 1 appearance; tied -> alphabetical.
    m = _matchups([("Banana", "Apple", "W")])
    assert top_n_archetypes(m, n=2) == ["Apple", "Banana"]


def test_map_to_bucket_returns_other_for_non_top_n():
    bucket = map_to_bucket(["IzzetProwess", "Mono-Green"], other_label="Other")
    assert bucket("IzzetProwess") == "IzzetProwess"
    assert bucket("Mono-Green") == "Mono-Green"
    assert bucket("RogueDeck") == "Other"
