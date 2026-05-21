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


import math
from mtg_scrape.build_matchup_matrix import compute_matrix, compute_win_rate


def test_compute_matrix_counts_wins_and_losses_per_cell():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "L"),
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    wins, losses = compute_matrix(long, ordered_labels=["IzzetProwess", "Mono-Green"])

    assert wins.loc["IzzetProwess", "Mono-Green"] == 2
    assert losses.loc["IzzetProwess", "Mono-Green"] == 1
    assert wins.loc["Mono-Green", "IzzetProwess"] == 1
    assert losses.loc["Mono-Green", "IzzetProwess"] == 2


def test_compute_matrix_diagonal_is_zero():
    m = _matchups([("IzzetProwess", "IzzetProwess", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess"])
    wins, losses = compute_matrix(long, ordered_labels=["IzzetProwess"])
    assert wins.loc["IzzetProwess", "IzzetProwess"] == 1
    assert losses.loc["IzzetProwess", "IzzetProwess"] == 1


def test_compute_win_rate_off_diagonal_is_wins_over_total():
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert wr.loc["A", "B"] == pytest.approx(2 / 3)
    assert wr.loc["B", "A"] == pytest.approx(1 / 3)


def test_compute_win_rate_diagonal_is_nan():
    wins = pd.DataFrame([[5, 2], [1, 5]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[5, 1], [2, 5]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert math.isnan(wr.loc["A", "A"])
    assert math.isnan(wr.loc["B", "B"])


def test_off_diagonal_symmetry_invariant():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "L"),
        ("IzzetProwess", "Mono-Green", "W"),
    ])
    labels = ["IzzetProwess", "Mono-Green"]
    long = to_long_frame(m, top_n=labels)
    wins, losses = compute_matrix(long, ordered_labels=labels)
    wr = compute_win_rate(wins, losses)
    assert wr.loc["IzzetProwess", "Mono-Green"] + wr.loc["Mono-Green", "IzzetProwess"] == pytest.approx(1.0)


def test_compute_win_rate_low_sample_cell_is_nan_when_zero_games():
    wins = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert math.isnan(wr.loc["A", "B"])


from pathlib import Path
from mtg_scrape.build_matchup_matrix import render_csvs


def test_render_csvs_writes_three_files(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    assert (tmp_path / "matchup_matrix.csv").exists()
    assert (tmp_path / "matchup_matrix_numeric.csv").exists()
    assert (tmp_path / "matchup_matrix_counts.csv").exists()


def test_string_csv_cells_format_percent_and_wl(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix.csv", index_col=0)
    assert df.loc["A", "B"] == "67% (2-1)"
    assert df.loc["B", "A"] == "33% (1-2)"
    assert df.loc["A", "A"] == "—"
    assert df.loc["B", "B"] == "—"


def test_counts_csv_uses_wl_string(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix_counts.csv", index_col=0)
    assert df.loc["A", "B"] == "2-1"
    assert df.loc["A", "A"] == "—"


def test_numeric_csv_has_win_rate_floats(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix_numeric.csv", index_col=0)
    assert df.loc["A", "B"] == pytest.approx(2 / 3)
    assert pd.isna(df.loc["A", "A"])


def test_empty_cell_renders_as_em_dash_in_string(tmp_path: Path):
    wins = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix.csv", index_col=0)
    assert df.loc["A", "B"] == "—"


from mtg_scrape.build_matchup_matrix import render_png


def test_render_png_writes_a_non_empty_file(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    out_path = tmp_path / "matchup_matrix.png"
    render_png(wins, losses, out_path=out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 1000  # non-trivial PNG, not a stub
