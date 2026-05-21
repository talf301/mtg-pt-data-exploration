"""Join decks.csv and matches.csv into matchups.csv (constructed-only) and players.csv.

matches.csv schema (from Task 8) uses string rounds, lowercase format ("standard"/"draft"),
and names in either canonical magic.gg form (for fetched players) or raw mtgelo
"Last, First" form (for unfetched players, where they appear only as opponents).
The resolver folds accents, case, whitespace, and comma-swap to bring everything
back to canonical magic.gg names.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from mtg_scrape.names import build_resolver, load_overrides


class UnresolvedNamesError(RuntimeError):
    """Raised when matches reference players that cannot be resolved to a decklist owner."""


def _round_sort_key(r) -> tuple[int, int]:
    """Sort key for string rounds: numeric swiss rounds first (in order), then top cut Q/S/F."""
    s = str(r)
    try:
        return (0, int(s))
    except ValueError:
        return (1, {"Q": 1, "S": 2, "F": 3}.get(s, 99))


def build_matchups(
    decks: pd.DataFrame,
    matches: pd.DataFrame,
    overrides: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Filter matches to Standard rounds and join archetype + Elo per side.

    Names in matches (from mtgeloproject) are resolved to canonical decks-side names
    via accent/case/comma folding (always) and the overrides map (if substantial
    differences exist). Raises UnresolvedNamesError if any resolution fails.
    """
    if overrides is None:
        overrides = {}

    canonical = decks["player_name"].tolist()
    resolver = build_resolver(canonical, overrides)

    working = matches.copy()
    working["player_a_resolved"] = working["player_a_name"].apply(resolver)
    working["player_b_resolved"] = working["player_b_name"].apply(resolver)

    unresolved = sorted(
        set(working.loc[working["player_a_resolved"].isna(), "player_a_name"].unique())
        | set(working.loc[working["player_b_resolved"].isna(), "player_b_name"].unique())
    )
    if unresolved:
        raise UnresolvedNamesError(
            "Players in matches.csv have no decklist in decks.csv. "
            "Add rows to data/name_overrides.csv (magic_gg_name, mtgelo_name) and re-run:\n  - "
            + "\n  - ".join(unresolved)
        )

    working["player_a"] = working["player_a_resolved"]
    working["player_b"] = working["player_b_resolved"]
    working = working.drop(columns=["player_a_resolved", "player_b_resolved"])

    standard = working[working["format"] == "standard"].copy()

    decks_idx = decks.set_index("player_name")
    standard["archetype_a"] = standard["player_a"].map(decks_idx["archetype_magicgg"])
    standard["archetype_b"] = standard["player_b"].map(decks_idx["archetype_magicgg"])
    standard = standard.rename(columns={
        "player_a_elo_pre": "elo_a_pre",
        "player_a_elo_post": "elo_a_post",
        "player_b_elo_pre": "elo_b_pre",
        "player_b_elo_post": "elo_b_post",
    })

    return standard[[
        "match_id", "round",
        "player_a", "archetype_a", "elo_a_pre", "elo_a_post",
        "player_b", "archetype_b", "elo_b_pre", "elo_b_post",
        "result", "game_score",
    ]].reset_index(drop=True)


def derive_players(
    matches: pd.DataFrame,
    canonical_names: list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Per-player starting_elo: elo_pre in their earliest round.

    If canonical_names is provided, raw mtgelo names get resolved to canonical
    magic.gg names; otherwise names pass through unchanged.
    """
    if overrides is None:
        overrides = {}

    a = matches[["round", "player_a_name", "player_a_elo_pre"]].rename(
        columns={"player_a_name": "player_name", "player_a_elo_pre": "elo_pre"})
    b = matches[["round", "player_b_name", "player_b_elo_pre"]].rename(
        columns={"player_b_name": "player_name", "player_b_elo_pre": "elo_pre"})
    long = pd.concat([a, b], ignore_index=True).dropna(subset=["elo_pre"])
    if long.empty:
        return pd.DataFrame(columns=["player_name", "starting_elo"])

    if canonical_names is not None:
        resolver = build_resolver(canonical_names, overrides)
        long["player_name"] = long["player_name"].apply(resolver)
        # Any names that didn't resolve become None; drop them silently — the
        # build_matchups path already enforces resolution for matchups.csv.
        long = long.dropna(subset=["player_name"])

    long["_sort"] = long["round"].apply(_round_sort_key)
    long_sorted = long.sort_values("_sort")
    first_per_player = long_sorted.drop_duplicates(subset=["player_name"], keep="first")
    return first_per_player[["player_name", "elo_pre"]].rename(
        columns={"elo_pre": "starting_elo"}).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decks", default="data/decks.csv")
    parser.add_argument("--matches", default="data/matches.csv")
    parser.add_argument("--overrides", default="data/name_overrides.csv")
    parser.add_argument("--matchups-out", default="data/matchups.csv")
    parser.add_argument("--players-out", default="data/players.csv")
    args = parser.parse_args()

    decks = pd.read_csv(args.decks)
    matches = pd.read_csv(args.matches, dtype={"round": str})  # rounds may look numeric
    overrides = load_overrides(Path(args.overrides))

    matchups = build_matchups(decks, matches, overrides=overrides)
    matchups.to_csv(args.matchups_out, index=False)
    print(f"Wrote {len(matchups)} matchups to {args.matchups_out}")

    players = derive_players(matches, canonical_names=decks["player_name"].tolist(), overrides=overrides)
    players.to_csv(args.players_out, index=False)
    print(f"Wrote {len(players)} players to {args.players_out}")


if __name__ == "__main__":
    main()
