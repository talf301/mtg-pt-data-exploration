# PT Secrets of Strixhaven scraper — design

**Date:** 2026-05-21
**Status:** Approved by user, ready for implementation planning
**Event:** Pro Tour Secrets of Strixhaven, Las Vegas, May 1–3 2026 (325 players, Standard + Booster Draft)

## Goal

Collect a complete, analyzable dataset of the PT covering, for every match played: who played whom, the result, both players' Elo before the match (with the delta), and both players' registered Standard decks and archetypes. The dataset is the input to downstream analysis isolating constructed-round matchups and cross-referencing decks.

## Sources

Hybrid, two scrapers:

- **magic.gg** — three surname-bucketed HTML pages list all 325 PT Standard decklists, each with an archetype label. Server-rendered, no anti-bot, official source.
  - `https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-a-f`
  - `…-m-r`, `…-s-z` (exact suffix list confirmed during implementation)
- **mtgeloproject.net** — per-player profile pages expose round-by-round match history including opponent, round number, format tag, result, and Elo delta. Server-rendered, no anti-bot.

The primary plan does **not** scrape melee.gg. It is anti-bot protected, its API is gated to event organizers, and the community scraper (`Badaro/MTGODecklistCache`) was archived June 2025 with its melee path broken. magic.gg covers decks; mtgeloproject covers matches + Elo. Melee is held in reserve as a Playwright-driven fallback for the matches half only — see the verification spike.

## Architecture

Two independent scrapers feeding a joiner, with a shared HTTP fetcher:

```
magic.gg (3 surname pages)  ── decks_scraper   ──→  data/decks.csv ─┐
                                                                    │ (player roster)
                                                                    ▼
mtgeloproject (search +     ── matches_scraper ──→  data/matches.csv
~325 player profiles)                                               │
                                                                    ▼
                                                       build_matchups ──→ data/matchups.csv
                                                       (filter to Standard,
                                                        join archetype + Elo per side)
```

The decks scrape runs first and produces the canonical roster of 325 player names. The matches scrape consumes that roster to know which mtgeloproject profiles to fetch, then walks each profile, extracting that player's PT Strixhaven matches with Elo + Δ. Matches are deduped by `(round, frozenset(player_a, player_b))`, merging the two Elo perspectives into a single row.

The "is there a mtgeloproject event page?" fallback is not needed — per-match Elos live on player profiles, so we walk profiles unconditionally.

## Components

### `mtg_scrape/fetch.py`
Thin `httpx`-based GET helper. On-disk cache keyed by URL hash, written to `cache/`. Polite rate limit (~1 req/sec). Retry with exponential backoff on transient errors. Cache hits short-circuit network entirely, making re-runs free and reproducible.

### `mtg_scrape/decks_magicgg.py`
Inputs: three magic.gg URLs.
Parses each page's decklist sections, extracting per player: `player_name`, `archetype_magicgg` (the deck name label magic.gg prints, e.g. "Selesnya Landfall"), `mainboard` (list of `qty, card`), `sideboard` (list of `qty, card`).
Output: `data/decks.csv`.

### `mtg_scrape/matches_mtgelo.py`
Inputs: roster of player names from `decks.csv`.
For each player:
1. Resolve name → mtgeloproject profile URL via the site's name search.
2. Fetch the profile page (cached).
3. Extract all matches tagged to the PT Strixhaven event: `round_number, format_tag, opponent_name, match_result, game_score?, elo_pre, elo_delta`.

Then dedupe across players: for each match, two profile views should appear (one from each side). Stitch them into a single row carrying both players' Elo + Δ. Matches that only appear from one side (e.g. an opponent we couldn't resolve) are kept with the missing side's Elo fields left null.

Output: `data/matches.csv`.

### `mtg_scrape/names.py`
Normalization helpers: case-fold, strip accents, collapse whitespace. Builds the canonical name → profile map used by `matches_mtgelo.py`. Honors `data/name_overrides.csv`, a manually maintained CSV of `magic_gg_name, mtgelo_name` rows for stylization mismatches the auto-resolver can't handle.

### `mtg_scrape/build_matchups.py`
Reads `decks.csv` and `matches.csv`.
Filters matches to Standard rounds (drops Booster Draft rounds).
Joins each side's archetype + decklist + pre-match Elo.
Surfaces any unresolved name mismatches as a loud printed report. Does **not** silently drop rows.
Derives `data/players.csv` (`player_name, starting_elo` = pre-round-1 Elo).
Output: `data/matchups.csv`.

## Schemas

### `decks.csv`
| column | type | notes |
|---|---|---|
| `player_name` | str | canonical name as printed on magic.gg |
| `archetype_magicgg` | str | the deck label magic.gg attaches |
| `mainboard` | str | serialized list, e.g. `"4 Llanowar Elves; 4 …"` |
| `sideboard` | str | same shape as mainboard |

### `matches.csv`
| column | type | notes |
|---|---|---|
| `round` | int | swiss round number, 1-based |
| `format` | str | `"Standard"` or `"Booster Draft"` |
| `player_a` | str | alphabetic-ordering of the two names (canonical) |
| `player_b` | str | the other one |
| `result` | str | from player_a's perspective: `"W"`, `"L"`, `"D"` |
| `game_score` | str | e.g. `"2-1"` if exposed; nullable |
| `player_a_elo_pre` | float | Elo entering this match |
| `player_a_elo_delta` | float | rating change from this match |
| `player_b_elo_pre` | float | nullable if only one side resolvable |
| `player_b_elo_delta` | float | nullable if only one side resolvable |

### `players.csv` (derived)
| column | type | notes |
|---|---|---|
| `player_name` | str |  |
| `starting_elo` | float | pre-round-1 Elo |

### `matchups.csv` (final, constructed-only)
| column | type | notes |
|---|---|---|
| `round` | int | Standard rounds only |
| `player_a` | str |  |
| `archetype_a` | str | from magic.gg |
| `elo_a_pre` | float |  |
| `player_b` | str |  |
| `archetype_b` | str |  |
| `elo_b_pre` | float |  |
| `result` | str | from player_a's perspective |

### `name_overrides.csv` (manual)
| column | type | notes |
|---|---|---|
| `magic_gg_name` | str |  |
| `mtgelo_name` | str |  |

## Storage layout

```
mtg-pt-data-exploration/
├── pyproject.toml              # uv-managed; deps: httpx, beautifulsoup4, pandas, pytest
├── README.md
├── mtg_scrape/
│   ├── __init__.py
│   ├── fetch.py
│   ├── decks_magicgg.py
│   ├── matches_mtgelo.py
│   ├── names.py
│   └── build_matchups.py
├── tests/                      # fixture-based parser tests
├── cache/                      # raw HTML, gitignored
├── data/                       # committed CSVs
│   ├── decks.csv
│   ├── matches.csv
│   ├── players.csv
│   ├── matchups.csv
│   └── name_overrides.csv
└── notebooks/
    └── exploration.ipynb       # downstream analysis
```

## Error handling

- **Transient HTTP errors:** `fetch.py` retries with backoff. Cache hit short-circuits.
- **Name-join misses:** `build_matchups` prints the unresolved pairs and exits non-zero. User adds rows to `name_overrides.csv` and re-runs. No silent drops.
- **One-sided matches:** kept with the resolvable side's Elo populated, the other side's Elo fields null.
- **Format tag missing or unreliable:** fall back to the known PT round structure (8 Booster Draft rounds + 8 Standard swiss rounds + Top 8 Standard) hardcoded as a sanity check.

## Verification spike (day-1, before full scrape)

Before committing to the full mtgeloproject scrape, manually verify on a known-recent Pro Tour event (a prior PT on the site):

1. Per-round per-match data is exposed on profile pages with opponent names.
2. Per-match Elo + Δ are present.
3. A workable name-search URL pattern exists.

If any of those fails, fall back to scraping melee.gg pairings via Playwright for the matches half. The decks half (magic.gg) is unaffected.

## Out of scope (explicit)

- Draft (limited) deck contents and pod composition. We capture *that* limited rounds happened but not what was drafted.
- Other Pro Tours. The scrapers are written against PT Strixhaven URLs and labels; generalizing to other PTs is deferred.
- Live updates. This is a one-shot scrape of a completed event.
- Special handling for the Top 8 single-elimination bracket. Top 8 matches are included in `matches.csv` and `matchups.csv` if they appear on player profiles (they are Standard with the same registered decks, so including them is correct), but no bracket reconstruction or additional metadata.

## Testing strategy

Each parser is tested against a saved HTML fixture in `tests/fixtures/` so tests do not depend on the live site. `fetch.py` is tested against a recorded response. Integration is verified manually via the verification spike and then by inspecting `matchups.csv` for sanity (e.g. row count ≈ 325 players × 8 Standard rounds ÷ 2 ≈ 1300 rows, modulo drops).

## Politeness

`fetch.py` rate-limits to roughly 1 req/sec and caches everything. Total request count is bounded: 3 magic.gg pages + ~325 profile fetches + ~325 search queries ≈ 700 requests, run once. Subsequent re-runs are cache hits unless cache is cleared.
