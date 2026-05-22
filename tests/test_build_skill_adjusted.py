import pytest
import pandas as pd

from mtg_scrape.build_skill_adjusted import _elo_expected, to_skill_long_frame


def test_elo_expected_is_50pct_at_zero_gap():
    assert _elo_expected(my_elo=1800.0, opp_elo=1800.0) == pytest.approx(0.5)


def test_elo_expected_is_60pct_at_200_gap_higher():
    # The defining anchor of mtgeloproject's scale.
    assert _elo_expected(my_elo=1800.0, opp_elo=1600.0) == pytest.approx(0.6, abs=1e-6)


def test_elo_expected_is_40pct_at_200_gap_lower():
    # Symmetric mirror: my_elo 200 below opponent -> 40% win rate.
    assert _elo_expected(my_elo=1600.0, opp_elo=1800.0) == pytest.approx(0.4, abs=1e-6)


def test_elo_expected_symmetric_sums_to_1():
    # For any gap, P(A wins) + P(B wins) == 1.0
    for my, opp in [(1500, 1700), (1900, 1500), (2000, 2050)]:
        a = _elo_expected(my, opp)
        b = _elo_expected(opp, my)
        assert a + b == pytest.approx(1.0, abs=1e-9)


def _matchups(rows):
    """Each row: (arch_a, arch_b, result, elo_a_pre, elo_b_pre)."""
    return pd.DataFrame(
        rows,
        columns=["archetype_a", "archetype_b", "result", "elo_a_pre", "elo_b_pre"],
    )


def test_long_frame_doubles_decided_non_mirror_rows():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 4  # 2 input rows x 2 perspectives, all kept


def test_long_frame_drops_draws():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("IzzetProwess", "Mono-Green", "D", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the W row's two perspectives


def test_long_frame_drops_mirrors():
    m = _matchups([
        ("IzzetProwess", "IzzetProwess", "W", 1800.0, 1700.0),
        ("IzzetProwess", "Mono-Green",   "W", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the non-mirror W row's two perspectives
    assert (long["my_arch"] == "IzzetProwess").any()
    assert (long["my_arch"] == "Mono-Green").any()


def test_long_frame_drops_rows_with_nan_elo():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, float("nan")),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the row with both elos present survives


def test_long_frame_mirror_perspective_flips_result_and_swaps_elos():
    m = _matchups([("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0)])
    long = to_skill_long_frame(m)
    forward = long[long["my_arch"] == "IzzetProwess"].iloc[0]
    assert forward["opp_arch"] == "Mono-Green"
    assert forward["result"] == "W"
    assert forward["my_elo"] == 1800.0
    assert forward["opp_elo"] == 1700.0
    mirror = long[long["my_arch"] == "Mono-Green"].iloc[0]
    assert mirror["opp_arch"] == "IzzetProwess"
    assert mirror["result"] == "L"
    assert mirror["my_elo"] == 1700.0
    assert mirror["opp_elo"] == 1800.0
