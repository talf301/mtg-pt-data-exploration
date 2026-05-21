from pathlib import Path
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
