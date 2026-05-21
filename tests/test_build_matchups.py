import math
import pandas as pd
import pytest

from mtg_scrape.build_matchups import build_matchups, derive_players, UnresolvedNamesError


def _decks_df():
    return pd.DataFrame([
        {"player_name": "Nathan Steuer", "archetype_magicgg": "Selesnya Landfall",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Christoffer Larsen", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])


def _matches_df():
    """matches.csv with new JSON-API schema: round is str, format is lowercase,
    columns player_a_name/player_b_name carry whichever form (canonical or raw mtgelo).
    """
    return pd.DataFrame([
        # round "1": Booster Draft (lowercase, should be filtered out)
        {"match_id": 1, "round": "1", "format": "draft", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "L", "game_score": "1-2",
         "player_a_elo_pre": 1850.0, "player_a_elo_post": 1840.0, "player_a_elo_delta": -10.0,
         "player_b_elo_pre": 1900.0, "player_b_elo_post": 1910.0, "player_b_elo_delta": 10.0},
        # round "4": Standard, lowercase
        {"match_id": 2, "round": "4", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "W", "game_score": "2-1",
         "player_a_elo_pre": 1845.0, "player_a_elo_post": 1860.0, "player_a_elo_delta": 15.0,
         "player_b_elo_pre": 1910.0, "player_b_elo_post": 1895.0, "player_b_elo_delta": -15.0},
    ])


def test_filters_to_standard_rounds_only():
    out = build_matchups(_decks_df(), _matches_df())
    assert list(out["round"]) == ["4"], "draft round should be excluded"


def test_joins_archetype_per_side():
    out = build_matchups(_decks_df(), _matches_df())
    row = out.iloc[0]
    assert row["archetype_a"] == "Izzet Prowess"      # Christoffer Larsen
    assert row["archetype_b"] == "Selesnya Landfall"  # Nathan Steuer


def test_joins_elo_per_side():
    out = build_matchups(_decks_df(), _matches_df())
    row = out.iloc[0]
    assert row["elo_a_pre"] == 1845.0
    assert row["elo_b_pre"] == 1910.0


def test_keeps_result_and_game_score_from_player_a_perspective():
    out = build_matchups(_decks_df(), _matches_df())
    row = out.iloc[0]
    assert row["result"] == "W"
    assert row["game_score"] == "2-1"


def test_resolves_mtgelo_last_comma_first_to_canonical():
    """matches.csv from Task 8 may carry raw 'Last, First' for unfetched players."""
    decks = pd.DataFrame([
        {"player_name": "Nathan Steuer", "archetype_magicgg": "Selesnya Landfall",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Christoffer Larsen", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])
    matches = pd.DataFrame([
        {"match_id": 1, "round": "4", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Larsen, Christoffer",  # raw mtgelo form
         "player_b_id": "zz14clya", "player_b_name": "Steuer, Nathan",
         "result": "W", "game_score": "2-1",
         "player_a_elo_pre": 1845.0, "player_a_elo_post": 1860.0, "player_a_elo_delta": 15.0,
         "player_b_elo_pre": 1910.0, "player_b_elo_post": 1895.0, "player_b_elo_delta": -15.0},
    ])
    out = build_matchups(decks, matches)
    row = out.iloc[0]
    assert row["player_a"] == "Christoffer Larsen"  # canonical magic.gg form
    assert row["player_b"] == "Nathan Steuer"
    assert row["archetype_a"] == "Izzet Prowess"


def test_raises_on_unresolved_name():
    matches = _matches_df().copy()
    matches.loc[1, "player_b_name"] = "Ghost, Player"  # not in decks
    with pytest.raises(UnresolvedNamesError) as exc:
        build_matchups(_decks_df(), matches)
    assert "Ghost" in str(exc.value)


def test_overrides_resolve_substantial_name_mismatches():
    decks = pd.DataFrame([
        {"player_name": "Sam Black", "archetype_magicgg": "Mardu Sacrifice",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Christoffer Larsen", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])
    matches = pd.DataFrame([
        {"match_id": 1, "round": "4", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "xxxxxxxx", "player_b_name": "Black, Samuel",  # mtgelo's name
         "result": "W", "game_score": "2-1",
         "player_a_elo_pre": 1845.0, "player_a_elo_post": 1860.0, "player_a_elo_delta": 15.0,
         "player_b_elo_pre": 1800.0, "player_b_elo_post": 1785.0, "player_b_elo_delta": -15.0},
    ])
    overrides = {"samuel black": "sam black"}  # as load_overrides would return
    out = build_matchups(decks, matches, overrides=overrides)
    assert out.iloc[0]["player_b"] == "Sam Black"
    assert out.iloc[0]["archetype_b"] == "Mardu Sacrifice"


def test_derive_players_starting_elo_uses_earliest_round():
    """starting_elo == player's elo_pre in their lowest-numeric-round match."""
    matches = pd.DataFrame([
        {"match_id": 1, "round": "1", "format": "draft", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "L", "game_score": "1-2",
         "player_a_elo_pre": 1850.0, "player_a_elo_post": 1840.0, "player_a_elo_delta": -10.0,
         "player_b_elo_pre": 1900.0, "player_b_elo_post": 1910.0, "player_b_elo_delta": 10.0},
        {"match_id": 2, "round": "4", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "W", "game_score": "2-1",
         "player_a_elo_pre": 1845.0, "player_a_elo_post": 1860.0, "player_a_elo_delta": 15.0,
         "player_b_elo_pre": 1910.0, "player_b_elo_post": 1895.0, "player_b_elo_delta": -15.0},
    ])
    players = derive_players(matches)
    by_name = players.set_index("player_name")
    assert by_name.loc["Christoffer Larsen", "starting_elo"] == 1850.0  # round "1" elo_pre
    assert by_name.loc["Nathan Steuer", "starting_elo"] == 1900.0


def test_derive_players_sorts_string_rounds_numerically():
    """Round '10' must sort after round '2', not before (lexicographic would say otherwise)."""
    matches = pd.DataFrame([
        # Player only appears in rounds '2' and '10'; starting_elo should be from round '2'
        {"match_id": 1, "round": "10", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "W", "game_score": "2-1",
         "player_a_elo_pre": 1900.0, "player_a_elo_post": 1910.0, "player_a_elo_delta": 10.0,
         "player_b_elo_pre": 1850.0, "player_b_elo_post": 1840.0, "player_b_elo_delta": -10.0},
        {"match_id": 2, "round": "2", "format": "standard", "table": 1,
         "player_a_id": "wrr61zbv", "player_a_name": "Christoffer Larsen",
         "player_b_id": "zz14clya", "player_b_name": "Nathan Steuer",
         "result": "L", "game_score": "0-2",
         "player_a_elo_pre": 1860.0, "player_a_elo_post": 1850.0, "player_a_elo_delta": -10.0,
         "player_b_elo_pre": 1810.0, "player_b_elo_post": 1820.0, "player_b_elo_delta": 10.0},
    ])
    players = derive_players(matches)
    by_name = players.set_index("player_name")
    assert by_name.loc["Christoffer Larsen", "starting_elo"] == 1860.0  # round "2" elo_pre, not "10"
