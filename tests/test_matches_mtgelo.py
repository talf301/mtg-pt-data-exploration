import json
from pathlib import Path

import pytest

from mtg_scrape.matches_mtgelo import parse_matches_json, ProfileMatch, EVENT_CODE

FIXTURE = Path(__file__).parent / "fixtures" / "mtgelo" / "api-matches-larsen.json"
LARSEN_ID = "wrr61zbv"
LARSEN_NAME = "Christoffer Larsen"


def test_returns_18_matches_for_larsen_at_ptsos():
    json_text = FIXTURE.read_text(encoding="utf-8")
    matches = parse_matches_json(json_text, player_name=LARSEN_NAME, player_id=LARSEN_ID)
    assert len(matches) == 18, f"Larsen played 18 ptsos matches; got {len(matches)}"


def test_match_carries_required_fields():
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    m = matches[0]
    assert isinstance(m, ProfileMatch)
    assert m.player_name == LARSEN_NAME
    assert m.player_id == LARSEN_ID
    assert isinstance(m.match_id, int)
    assert isinstance(m.round, str) and m.round
    assert m.format in {"standard", "draft", "sealed"}
    assert m.opponent_name and isinstance(m.opponent_name, str)
    assert m.opponent_id and isinstance(m.opponent_id, str)
    assert m.result in {"W", "L", "D"}
    assert m.game_score and isinstance(m.game_score, str)
    assert isinstance(m.elo_pre, float)
    assert isinstance(m.elo_post, float)
    assert isinstance(m.elo_delta, float)
    assert isinstance(m.opp_elo_pre, float)


def test_parses_finals_record_specifically():
    """The finals (match_id=4015653) was Larsen vs Steuer. Larsen lost 2-3, Elo Δ -21.70."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    finals = [m for m in matches if m.match_id == 4015653]
    assert len(finals) == 1
    f = finals[0]
    assert f.round == "F"
    assert f.format == "standard"
    assert f.opponent_name == "Steuer, Nathan"
    assert f.opponent_id == "zz14clya"
    assert f.result == "L"
    assert f.game_score == "2-3"
    assert f.elo_pre == 2361.56
    assert f.elo_post == 2339.86
    assert abs(f.elo_delta - (-21.70)) < 0.01


def test_filters_to_event_code():
    """Only ptsos matches should come back, not any other events Larsen played."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    assert all(m.event_code == EVENT_CODE for m in matches)


def test_round_remains_string():
    """Round must NOT be coerced to int; top cut uses Q/S/F."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    rounds = {m.round for m in matches}
    assert "F" in rounds
    assert "S" in rounds
    assert "1" in rounds  # as string, not int


def test_result_parsing_split():
    """'Lost 2-3' should split to result='L', game_score='2-3'."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    wins = [m for m in matches if m.result == "W"]
    losses = [m for m in matches if m.result == "L"]
    assert wins, "should have some wins"
    assert losses, "should have some losses"
    for m in matches:
        a, b = m.game_score.split("-")
        assert a.isdigit() and b.isdigit()


STEUER_FIXTURE = Path(__file__).parent / "fixtures" / "mtgelo" / "api-matches-steuer.json"
STEUER_ID = "zz14clya"
STEUER_NAME = "Nathan Steuer"


def test_steuer_perspective_of_finals_mirrors_larsen():
    """Cross-verification: the finals from Steuer's profile.

    Larsen lost 2-3 to Steuer; from Steuer's perspective the same match_id
    should show result='W', game_score='3-2', elo_delta ≈ +21.70, with
    opp_elo_pre equal to Larsen's elo_pre from the other fixture (2361.56).
    """
    matches = parse_matches_json(
        STEUER_FIXTURE.read_text(encoding="utf-8"),
        player_name=STEUER_NAME, player_id=STEUER_ID,
    )
    finals = next(m for m in matches if m.match_id == 4015653)
    assert finals.round == "F"
    assert finals.opponent_name == "Larsen, Christoffer"
    assert finals.opponent_id == "wrr61zbv"
    assert finals.result == "W"
    assert finals.game_score == "3-2"
    assert abs(finals.elo_delta - 21.70) < 0.01
    assert finals.opp_elo_pre == 2361.56  # Larsen's own elo_pre from the other fixture


def _synthetic_payload(result_str: str, with_nulls: bool = False) -> str:
    own_elo = {"start": 1500.0, "end": 1500.0} if not with_nulls else {"start": None, "end": None}
    opp_data = {"id": "abc", "opp": "Doe, Jane", "start": 1500.0 if not with_nulls else None}
    return json.dumps({EVENT_CODE: [{
        "match_id": 1, "round": "1", "table": 1, "format": "standard",
        "result": result_str, "own_elo": own_elo, "opp_data": opp_data,
    }]})


def test_draw_outcome_normalized_to_D():
    matches = parse_matches_json(
        _synthetic_payload("Draw 1-1"), player_name="x", player_id="y"
    )
    assert matches[0].result == "D"
    assert matches[0].game_score == "1-1"


def test_id_outcome_normalized_to_D():
    """Intentional draws are recorded as 'ID 0-0' (no game score). Map to D."""
    matches = parse_matches_json(
        _synthetic_payload("ID 0-0"), player_name="x", player_id="y"
    )
    assert matches[0].result == "D"
    assert matches[0].game_score == "0-0"


def test_unknown_outcome_raises_value_error():
    with pytest.raises(ValueError, match="unknown match outcome"):
        parse_matches_json(_synthetic_payload("Bye 0-0"), player_name="x", player_id="y")


def test_missing_elo_values_become_nan():
    import math
    matches = parse_matches_json(
        _synthetic_payload("Won 2-0", with_nulls=True), player_name="x", player_id="y"
    )
    m = matches[0]
    assert math.isnan(m.elo_pre)
    assert math.isnan(m.elo_post)
    assert math.isnan(m.elo_delta)
    assert math.isnan(m.opp_elo_pre)


# ===== Task 8: orchestrator tests =====

import math
from mtg_scrape.matches_mtgelo import (
    MergedMatch,
    find_player_id,
    merge_match_perspectives,
    scrape_all_players,
    split_name_for_search,
)

SEARCH_AUTOREDIRECT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mtgelo" / "search-results-steuer.html"
)
SEARCH_DISAMBIG_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mtgelo" / "search-results-larsen.html"
)


# ----- split_name_for_search -----

def test_split_name_for_search_simple():
    assert split_name_for_search("Nathan Steuer") == ("Steuer", "Nathan")


def test_split_name_for_search_with_middle():
    # last word is surname; everything before is first/middle
    assert split_name_for_search("Jose Maria Rodriguez") == ("Rodriguez", "Jose Maria")


def test_split_name_for_search_handles_accents():
    # don't strip accents on the search URL; pass through verbatim
    assert split_name_for_search("Javier Domínguez") == ("Domínguez", "Javier")


# ----- find_player_id -----

class _FakeFetcher:
    """Maps URLs to fixture HTML for offline testing of find_player_id."""
    def __init__(self, url_map: dict[str, str]):
        self._map = url_map

    def get(self, url: str) -> str:
        return self._map[url]


def test_find_player_id_auto_redirect_extracts_playerid_from_astro_island():
    fetcher = _FakeFetcher({
        "https://mtgeloproject.net/search/Steuer/Nathan":
            SEARCH_AUTOREDIRECT_FIXTURE.read_text(encoding="utf-8"),
    })
    assert find_player_id(fetcher, "Nathan Steuer") == "zz14clya"


def test_find_player_id_disambig_picks_ptsos_row():
    fetcher = _FakeFetcher({
        "https://mtgeloproject.net/search/Larsen/Christoffer":
            SEARCH_DISAMBIG_FIXTURE.read_text(encoding="utf-8"),
    })
    # Christoffer Larsen's profile is wrr61zbv per the spike notes; he played PT SOS.
    assert find_player_id(fetcher, "Christoffer Larsen") == "wrr61zbv"


# ----- merge_match_perspectives -----

def _pm(player_name, player_id, opponent_name, opponent_id, result, elo_pre, elo_post,
        opp_elo_pre, match_id=1, round_="4", fmt="standard", game_score="2-1", table=1):
    return ProfileMatch(
        player_name=player_name, player_id=player_id, match_id=match_id,
        round=round_, table=table, format=fmt,
        opponent_name=opponent_name, opponent_id=opponent_id,
        result=result, game_score=game_score,
        elo_pre=elo_pre, elo_post=elo_post, elo_delta=round(elo_post - elo_pre, 4),
        opp_elo_pre=opp_elo_pre,
    )


def test_merge_two_perspectives_dedupes_by_match_id():
    a = _pm("Nathan Steuer", "zz14clya", "Larsen, Christoffer", "wrr61zbv",
            "W", 1850.0, 1862.0, 1830.0)
    b = _pm("Christoffer Larsen", "wrr61zbv", "Steuer, Nathan", "zz14clya",
            "L", 1830.0, 1818.0, 1850.0)
    merged = merge_match_perspectives([a, b])
    assert len(merged) == 1
    m = merged[0]
    # Order by player_id ascending: "wrr61zbv" < "zz14clya" -> Larsen is player_a
    assert m.player_a_id == "wrr61zbv"
    assert m.player_b_id == "zz14clya"
    assert m.player_a_name == "Christoffer Larsen"  # canonical magic.gg form
    assert m.player_b_name == "Nathan Steuer"
    assert m.result == "L"  # Larsen lost
    assert m.player_a_elo_pre == 1830.0
    assert m.player_a_elo_post == 1818.0
    assert m.player_b_elo_pre == 1850.0
    assert m.player_b_elo_post == 1862.0


def test_merge_single_sided_fills_opponent_elo_pre_from_opp_data():
    # Only fetched Steuer's perspective; Larsen was unresolved.
    only = _pm("Nathan Steuer", "zz14clya", "Larsen, Christoffer", "wrr61zbv",
               "W", 1850.0, 1862.0, 1830.0)
    merged = merge_match_perspectives([only])
    assert len(merged) == 1
    m = merged[0]
    # player_a still ordered by id ascending; Larsen's id wins
    assert m.player_a_id == "wrr61zbv"
    assert m.player_a_name == "Larsen, Christoffer"  # raw mtgelo form, since we never fetched
    assert m.player_a_elo_pre == 1830.0  # from opp_data.start
    assert math.isnan(m.player_a_elo_post)
    assert math.isnan(m.player_a_elo_delta)
    assert m.player_b_id == "zz14clya"
    assert m.player_b_name == "Nathan Steuer"
    assert m.player_b_elo_pre == 1850.0
    assert m.player_b_elo_post == 1862.0
    assert m.result == "L"  # flipped from Steuer's "W" because Larsen is player_a


def test_merge_carries_match_metadata():
    a = _pm("Nathan Steuer", "zz14clya", "Larsen, Christoffer", "wrr61zbv",
            "W", 1850.0, 1862.0, 1830.0, match_id=4015653, round_="F",
            fmt="standard", game_score="3-2", table=1)
    merged = merge_match_perspectives([a])
    m = merged[0]
    assert m.match_id == 4015653
    assert m.round == "F"
    assert m.format == "standard"
    assert m.table == 1
    # game_score is from player_a's perspective; player_a is Larsen, who lost 2-3
    assert m.game_score == "2-3"


# ----- _flip_game_score -----

def test_flip_game_score_handles_normal_score():
    from mtg_scrape.matches_mtgelo import _flip_game_score
    assert _flip_game_score("2-3") == "3-2"
    assert _flip_game_score("0-2") == "2-0"


def test_flip_game_score_passes_through_empty_string():
    from mtg_scrape.matches_mtgelo import _flip_game_score
    assert _flip_game_score("") == ""


def test_flip_game_score_raises_on_malformed():
    from mtg_scrape.matches_mtgelo import _flip_game_score
    with pytest.raises(ValueError):
        _flip_game_score("2-1-0")
    with pytest.raises(ValueError):
        _flip_game_score("abc")


# ----- scrape_all_players -----

def test_scrape_all_players_skips_unresolved_and_continues():
    """If find_player_id returns None for one roster entry, that name is collected as
    unresolved and the next roster entry still gets processed."""
    api_url_steuer = "https://mtgeloproject.net/api/players/zz14clya/matches"
    search_url_steuer = "https://mtgeloproject.net/search/Steuer/Nathan"
    # Empty-result search for unresolvable player
    search_url_phantom = "https://mtgeloproject.net/search/Player/Phantom"

    fetcher = _FakeFetcher({
        search_url_phantom: "<html><body><main>No matches found.</main></body></html>",
        search_url_steuer: SEARCH_AUTOREDIRECT_FIXTURE.read_text(encoding="utf-8"),
        api_url_steuer: (Path(__file__).parent / "fixtures" / "mtgelo" /
                        "api-matches-steuer.json").read_text(encoding="utf-8"),
    })
    perspectives, unresolved, unresolved_opp_count = scrape_all_players(
        fetcher, ["Phantom Player", "Nathan Steuer"]
    )
    assert unresolved == ["Phantom Player"]
    assert isinstance(unresolved_opp_count, int)
    assert len(perspectives) > 0  # Steuer's matches were collected
    assert all(p.player_name == "Nathan Steuer" for p in perspectives)
