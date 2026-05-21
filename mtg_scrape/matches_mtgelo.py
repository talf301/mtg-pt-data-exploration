"""Scrape mtgeloproject.net for PT Secrets of Strixhaven match data via its JSON API.

This module:
  1. Defines the ProfileMatch dataclass capturing one match as fetched from one
     player's perspective.
  2. Provides parse_matches_json() — converts the JSON returned by
     /api/players/<id>/matches into ProfileMatch rows for the ptsos event.
  3. Orchestration (Task 8): name -> player_id lookup via the mtgelo /search/
     route, walk all PT Strixhaven roster profiles via the JSON API, dedupe
     two perspectives per match, write data/matches.csv.
"""
from __future__ import annotations

import csv
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol
from urllib.parse import quote

from bs4 import BeautifulSoup


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
        elo_pre = _to_float_or_nan(own_elo.get("start"))
        elo_post = _to_float_or_nan(own_elo.get("end"))
        opp_elo_pre = _to_float_or_nan(opp_data.get("start"))

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
    """Map mtgeloproject's outcome word to 'W' / 'L' / 'D'.

    mtgeloproject also emits ``"ID"`` (intentional draw) as a standalone result
    with no game score; treat that as a draw. Raises ValueError on truly
    unknown input so byes/forfeits or future mtgelo strings surface as
    failures rather than silent draws.
    """
    w = word.strip().lower()
    if w in {"won"}:
        return "W"
    if w in {"lost", "loss"}:
        return "L"
    if w in {"draw", "drew", "id"}:
        return "D"
    raise ValueError(f"unknown match outcome word: {word!r}")


def _to_float_or_nan(v: object) -> float:
    """Convert v to float, returning NaN if v is None or not numeric.

    mtgeloproject occasionally omits an elo value (e.g. for byes); we want
    to keep the row rather than crash. NaN propagates obviously through
    downstream aggregations.
    """
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# ============================================================
# Task 8: name search + orchestrator
# ============================================================

SEARCH_BASE = "https://mtgeloproject.net/search/{last}/{first}"
MATCHES_API_BASE = "https://mtgeloproject.net/api/players/{player_id}/matches"


class _FetcherProtocol(Protocol):
    def get(self, url: str) -> str: ...


def split_name_for_search(name: str) -> tuple[str, str]:
    """Split a 'First [Middle] Last' magic.gg name into (Last, First+Middle).

    mtgeloproject's search route is /search/<LastName>/<FirstName>. Most PT
    players have two-word names; for multi-word names we treat the trailing
    word as the surname.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        raise ValueError(f"need at least two words to split as Last/First: {name!r}")
    last = parts[-1]
    first = " ".join(parts[:-1])
    return last, first


def find_player_id(fetcher: _FetcherProtocol, magic_gg_name: str) -> str | None:
    """Resolve a magic.gg-canonical name to an mtgeloproject player_id.

    Strategy:
      - GET /search/<Last>/<First>. Two response shapes:
      - Auto-redirect: response IS the profile page. Look for the <astro-island
        component-url="/_astro/Profile..."> and parse its props.
      - Disambig page: parse <a href="/profile/<id>"> rows. Prefer the row whose
        adjacent "last event" cell text contains "ptsos".

    Returns the 8-char player_id, or None if we can't decide.
    """
    last, first = split_name_for_search(magic_gg_name)
    url = SEARCH_BASE.format(last=quote(last), first=quote(first))
    response_html = fetcher.get(url)
    soup = BeautifulSoup(response_html, "lxml")

    # Case 1: auto-redirected to the profile page.
    pid = _extract_playerid_from_astro_island(soup)
    if pid:
        return pid

    # Case 2: disambiguation table.
    return _pick_disambig_row(soup)


def _extract_playerid_from_astro_island(soup: BeautifulSoup) -> str | None:
    """Look for an <astro-island> whose component-url references the Profile bundle.

    The element has a `props` attribute holding HTML-entity-escaped JSON; one of
    the keys is `playerid`. Astro often wraps scalar values as ``[type, value]``
    pairs, so we accept either a bare string or such a tuple. Returns the
    8-char id string or None.
    """
    for island in soup.find_all("astro-island"):
        comp = island.get("component-url", "")
        if "/_astro/Profile" not in comp:
            continue
        props_raw = island.get("props", "")
        if not props_raw:
            continue
        try:
            props = json.loads(html.unescape(props_raw))
        except json.JSONDecodeError:
            continue
        pid = _walk_for_key(props, "playerid")
        # Astro wraps scalars as [type, value] (e.g. [0, "zz14clya"])
        if isinstance(pid, list) and len(pid) == 2 and isinstance(pid[1], str):
            pid = pid[1]
        if isinstance(pid, str) and re.fullmatch(r"[a-z0-9]{8}", pid):
            return pid
    return None


def _walk_for_key(obj: object, key: str) -> object:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _walk_for_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _walk_for_key(v, key)
            if found is not None:
                return found
    return None


def _pick_disambig_row(soup: BeautifulSoup) -> str | None:
    """Look at the search-results grid for an <a href="/profile/<id>"> link whose
    row's "last event" cell mentions ptsos.

    The grid has three columns (name | rating | last event) laid out as a flat
    sequence of direct-child <div> cells in a container with class
    ``grid grid-cols-[1fr_auto_auto]``. We chunk those cells in triples and pick
    the row whose 3rd cell text contains ``ptsos`` (case-insensitive).
    """
    grid = soup.select_one("div.grid")
    if grid is None:
        return None
    cells = [c for c in grid.find_all("div", recursive=False)]
    # Drop the 3 header cells (name/rating/last event).
    if not cells:
        return None
    if len(cells) >= 3 and cells[0].get_text(strip=True).lower() == "name":
        cells = cells[3:]

    # Group remaining cells in triples (name, rating, last_event).
    candidates: list[tuple[str, str]] = []  # (player_id, last_event_text)
    for i in range(0, len(cells) - 2, 3):
        name_cell, _rating_cell, last_event_cell = cells[i], cells[i + 1], cells[i + 2]
        a = name_cell.find("a", href=re.compile(r"^/profile/[a-z0-9]{8}"))
        if a is None:
            continue
        m = re.match(r"^/profile/([a-z0-9]{8})", a["href"])
        if not m:
            continue
        pid = m.group(1)
        last_event = last_event_cell.get_text(strip=True).lower()
        candidates.append((pid, last_event))

    # Prefer a row whose last-event cell mentions ptsos.
    for pid, last_event in candidates:
        if re.search(r"\bptsos\b", last_event):
            return pid
    # Fall back to a unique id if there's only one candidate.
    unique = {pid for pid, _ in candidates}
    if len(unique) == 1:
        return unique.pop()
    return None


@dataclass
class MergedMatch:
    """One dedupe-merged match across both player perspectives.

    player_a is the side whose mtgeloproject player_id sorts lexicographically
    first; player_b is the other. If we fetched that player's perspective, the
    name field carries the canonical magic.gg form; otherwise it carries the
    raw 'Last, First' string mtgelo exposed via the opponent's opp_data.
    """
    match_id: int
    round: str
    format: str
    table: int | None
    player_a_id: str
    player_a_name: str
    player_b_id: str
    player_b_name: str
    result: str               # W/L/D from player_a's perspective
    game_score: str           # from player_a's perspective ("a-b")
    player_a_elo_pre: float
    player_a_elo_post: float
    player_a_elo_delta: float
    player_b_elo_pre: float
    player_b_elo_post: float
    player_b_elo_delta: float


def merge_match_perspectives(rows: Iterable[ProfileMatch]) -> list[MergedMatch]:
    """Group ProfileMatch records by match_id, merging one or two perspectives per match.

    Determines player_a/player_b by lexicographic comparison of mtgeloproject
    player_ids. Result, game_score, and Elo info reflect player_a's perspective;
    fields the unfetched side leaves unfilled (elo_post / elo_delta) become NaN.
    """
    by_match: dict[int, list[ProfileMatch]] = {}
    for r in rows:
        by_match.setdefault(r.match_id, []).append(r)

    merged: list[MergedMatch] = []
    nan = float("nan")
    for match_id, perspectives in by_match.items():
        ids = sorted({pid for r in perspectives for pid in (r.player_id, r.opponent_id)})
        if len(ids) != 2:
            # corrupt (mirror match where player_id == opponent_id, or missing opponent)
            continue
        a_id, b_id = ids[0], ids[1]

        from_a = next((r for r in perspectives if r.player_id == a_id), None)
        from_b = next((r for r in perspectives if r.player_id == b_id), None)
        if from_a is None and from_b is None:
            continue

        if from_a is not None:
            a_name = from_a.player_name
        else:
            a_name = from_b.opponent_name  # raw "Last, First" via b's opp_data
        if from_b is not None:
            b_name = from_b.player_name
        else:
            b_name = from_a.opponent_name

        # Result + game_score from player_a's perspective
        if from_a is not None:
            result_a = from_a.result
            game_score_a = from_a.game_score
        else:
            result_a = {"W": "L", "L": "W", "D": "D"}[from_b.result]
            game_score_a = _flip_game_score(from_b.game_score)

        # Elo numbers
        if from_a is not None:
            a_elo_pre = from_a.elo_pre
            a_elo_post = from_a.elo_post
            a_elo_delta = from_a.elo_delta
        else:
            a_elo_pre = from_b.opp_elo_pre
            a_elo_post = nan
            a_elo_delta = nan

        if from_b is not None:
            b_elo_pre = from_b.elo_pre
            b_elo_post = from_b.elo_post
            b_elo_delta = from_b.elo_delta
        else:
            b_elo_pre = from_a.opp_elo_pre
            b_elo_post = nan
            b_elo_delta = nan

        sample = from_a or from_b
        merged.append(MergedMatch(
            match_id=match_id,
            round=sample.round,
            format=sample.format,
            table=sample.table,
            player_a_id=a_id,
            player_a_name=a_name,
            player_b_id=b_id,
            player_b_name=b_name,
            result=result_a,
            game_score=game_score_a,
            player_a_elo_pre=a_elo_pre,
            player_a_elo_post=a_elo_post,
            player_a_elo_delta=a_elo_delta,
            player_b_elo_pre=b_elo_pre,
            player_b_elo_post=b_elo_post,
            player_b_elo_delta=b_elo_delta,
        ))
    merged.sort(key=lambda m: (m.round, m.player_a_id))
    return merged


def _flip_game_score(score: str) -> str:
    """'2-3' -> '3-2'. Returns empty string unchanged. Raises ValueError on malformed input."""
    if score == "":
        return ""
    m = re.fullmatch(r"(\d+)-(\d+)", score)
    if not m:
        raise ValueError(f"unexpected game_score format: {score!r}")
    return f"{m.group(2)}-{m.group(1)}"


def scrape_all_players(
    fetcher: _FetcherProtocol,
    roster: list[str],
) -> tuple[list[ProfileMatch], list[str], int]:
    """Resolve each magic.gg name, fetch matches JSON, dedupe.

    Returns (all_perspectives, unresolved_names, count_unresolved_opponents).
    The third return value is the number of distinct opponent player_ids that
    appear in fetched matches but were never fetched themselves — i.e. potential
    invisible-match cases.
    """
    all_perspectives: list[ProfileMatch] = []
    unresolved: list[str] = []
    fetched_ids: set[str] = set()
    seen_opponent_ids: set[str] = set()

    for name in roster:
        try:
            pid = find_player_id(fetcher, name)
        except ValueError:
            unresolved.append(name)
            continue
        if not pid:
            unresolved.append(name)
            continue
        fetched_ids.add(pid)
        api_url = MATCHES_API_BASE.format(player_id=pid)
        body = fetcher.get(api_url)
        new_rows = parse_matches_json(body, player_name=name, player_id=pid)
        all_perspectives.extend(new_rows)
        for row in new_rows:
            seen_opponent_ids.add(row.opponent_id)

    unresolved_opponent_count = len(seen_opponent_ids - fetched_ids)
    return all_perspectives, unresolved, unresolved_opponent_count


def write_matches_csv(matches: list[MergedMatch], out_path: Path) -> None:
    """Write merged matches to CSV, rendering NaN as empty cells."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _fmt(v: float) -> str:
        if isinstance(v, float) and math.isnan(v):
            return ""
        return str(v)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "match_id", "round", "format", "table",
            "player_a_id", "player_a_name", "player_b_id", "player_b_name",
            "result", "game_score",
            "player_a_elo_pre", "player_a_elo_post", "player_a_elo_delta",
            "player_b_elo_pre", "player_b_elo_post", "player_b_elo_delta",
        ])
        for m in matches:
            w.writerow([
                m.match_id, m.round, m.format, "" if m.table is None else m.table,
                m.player_a_id, m.player_a_name, m.player_b_id, m.player_b_name,
                m.result, m.game_score,
                _fmt(m.player_a_elo_pre), _fmt(m.player_a_elo_post), _fmt(m.player_a_elo_delta),
                _fmt(m.player_b_elo_pre), _fmt(m.player_b_elo_post), _fmt(m.player_b_elo_delta),
            ])


def _load_roster(decks_path: Path) -> list[str]:
    with decks_path.open("r", encoding="utf-8", newline="") as f:
        return [row["player_name"] for row in csv.DictReader(f)]


def main() -> None:
    import argparse

    from mtg_scrape.fetch import Fetcher

    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--decks", default="data/decks.csv")
    parser.add_argument("--out", default="data/matches.csv")
    args = parser.parse_args()

    fetcher = Fetcher(cache_dir=Path(args.cache_dir), min_interval_s=1.0)
    roster = _load_roster(Path(args.decks))
    perspectives, unresolved, unresolved_opp_count = scrape_all_players(fetcher, roster)
    merged = merge_match_perspectives(perspectives)
    write_matches_csv(merged, Path(args.out))

    print(f"Wrote {len(merged)} matches to {args.out}")
    if unresolved:
        print(f"WARNING: {len(unresolved)} players could not be resolved on mtgeloproject:")
        for n in unresolved:
            print(f"  - {n}")
        print(f"  ({unresolved_opp_count} distinct opponent IDs appear in fetched matches "
              f"but were never fetched directly; their matches against each other are invisible.)")
        print("Note: single-sided rows are still captured via opponents' fetches.")


if __name__ == "__main__":
    main()
