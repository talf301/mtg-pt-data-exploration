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


from mtg_scrape.build_matchup_matrix import to_long_frame


def test_to_long_frame_doubles_row_count():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("Mono-Green", "IzzetProwess", "L"),
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    assert len(long) == 4  # 2 input rows × 2 perspectives


def test_to_long_frame_flips_result_on_mirror_row():
    m = _matchups([("IzzetProwess", "Mono-Green", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    # Forward perspective: my_arch=IzzetProwess, result=W
    forward = long[long["my_arch"] == "IzzetProwess"].iloc[0]
    assert forward["opp_arch"] == "Mono-Green"
    assert forward["result"] == "W"
    # Mirror perspective: my_arch=Mono-Green, result flipped to L
    mirror = long[long["my_arch"] == "Mono-Green"].iloc[0]
    assert mirror["opp_arch"] == "IzzetProwess"
    assert mirror["result"] == "L"


def test_to_long_frame_drops_draws():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "D"),  # this one drops both perspectives
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    assert len(long) == 2  # only the W row's two perspectives survive
    assert "D" not in long["result"].values


def test_to_long_frame_buckets_non_top_n_to_other():
    m = _matchups([("IzzetProwess", "RogueDeck", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess"])
    rogue_rows = long[long["my_arch"] == "Other"]
    assert len(rogue_rows) == 1
    assert rogue_rows.iloc[0]["opp_arch"] == "IzzetProwess"
    assert rogue_rows.iloc[0]["result"] == "L"  # flipped from input W
