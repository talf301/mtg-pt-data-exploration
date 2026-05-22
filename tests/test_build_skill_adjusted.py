import pytest

from mtg_scrape.build_skill_adjusted import _elo_expected


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
