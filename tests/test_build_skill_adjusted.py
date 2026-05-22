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


from mtg_scrape.build_skill_adjusted import compute_archetype_summary


def test_summary_has_one_row_per_archetype():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long)
    assert set(summary["archetype"]) == {"IzzetProwess", "Mono-Green"}


def test_summary_observed_counts():
    # Izzet wins both. Each match contributes 1 observed W for Izzet, 1 L for Mono-Green.
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    assert int(summary.loc["IzzetProwess", "observed_wins"]) == 2
    assert int(summary.loc["IzzetProwess", "observed_losses"]) == 0
    assert int(summary.loc["Mono-Green", "observed_wins"]) == 0
    assert int(summary.loc["Mono-Green", "observed_losses"]) == 2


def test_summary_expected_counts_at_tied_elo_match_observed():
    """At zero Elo gap, expected = observed for each side."""
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    assert summary.loc["IzzetProwess", "expected_wins"] == pytest.approx(1.0)
    assert summary.loc["IzzetProwess", "expected_losses"] == pytest.approx(1.0)
    assert summary.loc["Mono-Green", "expected_wins"] == pytest.approx(1.0)
    assert summary.loc["Mono-Green", "expected_losses"] == pytest.approx(1.0)


def test_summary_residual_is_observed_minus_expected_winrate():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    # Izzet observed 2-0 (100%), expected 50% -> residual +0.5
    assert summary.loc["IzzetProwess", "observed_wr"] == pytest.approx(1.0)
    assert summary.loc["IzzetProwess", "expected_wr"] == pytest.approx(0.5)
    assert summary.loc["IzzetProwess", "residual"] == pytest.approx(0.5)


def test_summary_zero_sum_invariant():
    """Sum of observed wins == sum of observed losses == sum of expected wins == sum of expected losses."""
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1850.0, 1700.0),
        ("IzzetProwess", "Mono-Green", "L", 1700.0, 1850.0),
        ("Selesnya",     "IzzetProwess", "W", 1750.0, 1750.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long)
    total_obs_w = summary["observed_wins"].sum()
    total_obs_l = summary["observed_losses"].sum()
    total_exp_w = summary["expected_wins"].sum()
    total_exp_l = summary["expected_losses"].sum()
    assert total_obs_w == total_obs_l == pytest.approx(total_exp_w) == pytest.approx(total_exp_l)


def test_summary_overperforming_deck_has_positive_residual():
    """A deck piloted by lower-Elo players that wins more than expected should have a positive residual."""
    # Izzet at 1500 always beats Mono-Green at 1900 (huge skill gap, but Izzet wins all 3).
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    assert summary.loc["IzzetProwess", "residual"] > 0.5  # observed 100%, expected ~14%
    assert summary.loc["Mono-Green", "residual"] < -0.5


from pathlib import Path
from mtg_scrape.build_skill_adjusted import render_csv


def test_render_csv_writes_file_sorted_by_residual_desc(tmp_path: Path):
    summary = pd.DataFrame([
        {"archetype": "A", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 4.0, "expected_losses": 6.0,
         "expected_wr": 0.4, "residual": 0.10},
        {"archetype": "B", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 6.0, "expected_losses": 4.0,
         "expected_wr": 0.6, "residual": -0.10},
        {"archetype": "C", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 5.0, "expected_losses": 5.0,
         "expected_wr": 0.5, "residual": 0.0},
    ])
    out = tmp_path / "archetype_skill_adjusted.csv"
    render_csv(summary, out)
    assert out.exists()
    df = pd.read_csv(out)
    # Sorted by residual descending: A (+0.10), C (0.0), B (-0.10)
    assert list(df["archetype"]) == ["A", "C", "B"]


def test_render_csv_preserves_all_columns(tmp_path: Path):
    summary = pd.DataFrame([{
        "archetype": "A", "games": 10, "observed_wins": 5, "observed_losses": 5,
        "observed_wr": 0.5, "expected_wins": 4.0, "expected_losses": 6.0,
        "expected_wr": 0.4, "residual": 0.10,
    }])
    out = tmp_path / "summary.csv"
    render_csv(summary, out)
    df = pd.read_csv(out)
    expected_cols = ["archetype", "games", "observed_wins", "observed_losses",
                     "observed_wr", "expected_wins", "expected_losses",
                     "expected_wr", "residual"]
    assert list(df.columns) == expected_cols
