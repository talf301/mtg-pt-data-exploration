"""Scrape mtgeloproject.net for PT Secrets of Strixhaven match data via its JSON API.

This module:
  1. Defines the ProfileMatch dataclass capturing one match as fetched from one
     player's perspective.
  2. Provides parse_matches_json() — converts the JSON returned by
     /api/players/<id>/matches into ProfileMatch rows for the ptsos event.
  3. (In Task 8) Adds orchestration: name -> player_id lookup, walk all 325
     profiles, dedupe two perspectives per match, write data/matches.csv.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


EVENT_CODE = "ptsos"  # mtgeloproject's internal code for Pro Tour Secrets of Strixhaven


@dataclass
class ProfileMatch:
    """One match as fetched from one player's matches API response."""
    player_name: str        # canonical name from magic.gg (passed in by caller)
    player_id: str          # mtgeloproject player slug
    match_id: int           # stable global id; dedupe key across perspectives
    round: str              # "1".."15" for swiss; "Q"/"S"/"F" for top cut
    table: int | None
    format: str             # "standard" / "draft" / "sealed"
    opponent_name: str      # raw mtgelo "Last, First" string
    opponent_id: str        # mtgeloproject opponent slug
    result: str             # "W" / "L" / "D" from player's perspective
    game_score: str         # "2-1", "0-2", etc.
    elo_pre: float
    elo_post: float
    elo_delta: float
    opp_elo_pre: float
    event_code: str = EVENT_CODE


def parse_matches_json(
    json_text: str,
    player_name: str,
    player_id: str,
) -> list[ProfileMatch]:
    """Parse one /api/players/<id>/matches response into ProfileMatch rows for PT SOS."""
    payload = json.loads(json_text)
    raw_matches = payload.get(EVENT_CODE, [])
    rows: list[ProfileMatch] = []
    for m in raw_matches:
        result_str = m.get("result", "")
        outcome_word, _, game_score = result_str.partition(" ")
        result = _normalize_outcome(outcome_word)

        own_elo = m.get("own_elo") or {}
        opp_data = m.get("opp_data") or {}
        elo_pre = float(own_elo.get("start"))
        elo_post = float(own_elo.get("end"))
        opp_start = opp_data.get("start")
        opp_elo_pre = float(opp_start) if opp_start is not None else float("nan")

        rows.append(ProfileMatch(
            player_name=player_name,
            player_id=player_id,
            match_id=int(m["match_id"]),
            round=str(m["round"]),
            table=int(m["table"]) if m.get("table") is not None else None,
            format=str(m.get("format", "")),
            opponent_name=str(opp_data.get("opp", "")),
            opponent_id=str(opp_data.get("id", "")),
            result=result,
            game_score=game_score,
            elo_pre=elo_pre,
            elo_post=elo_post,
            elo_delta=round(elo_post - elo_pre, 4),
            opp_elo_pre=opp_elo_pre,
        ))
    return rows


def _normalize_outcome(word: str) -> str:
    """'Won' -> 'W', 'Lost' -> 'L', 'Draw' -> 'D'."""
    w = word.strip().lower()
    if w.startswith("won"):
        return "W"
    if w.startswith("lost") or w.startswith("loss"):
        return "L"
    return "D"
