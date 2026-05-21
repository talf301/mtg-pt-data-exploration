# mtgeloproject spike — findings (2026-05-21)

## Decision

**PROCEED** with the mtgeloproject pipeline (Task 6 and beyond) — but with a major plan
revision: **the parser should hit the JSON API directly, not scrape rendered HTML.**

All five required data points are present, and the site exposes a clean, undocumented
JSON API used by its own React profile component. Using the API removes ~all of the
HTML/CSS-selector fragility that Task 7 was originally going to deal with.

## URL patterns (verified)

| Purpose | URL |
| --- | --- |
| Home | `https://mtgeloproject.net/` |
| FAQ | `https://mtgeloproject.net/faq` |
| Leaders | `https://mtgeloproject.net/leaders/all` |
| Search (HTML) | `https://mtgeloproject.net/search/<LastName>/<FirstName>` — `*` is the wildcard for either part |
| Player profile (HTML, mostly empty — see below) | `https://mtgeloproject.net/profile/<player_id>` |
| **Player matches (JSON API)** | `https://mtgeloproject.net/api/players/<player_id>/matches` |
| Player events (JSON API) | `https://mtgeloproject.net/api/players/<player_id>/events` |

`<player_id>` is an 8-character lowercase-alphanumeric slug (e.g., `wrr61zbv`,
`zz14clya`). It's stable, opaque, and is what the React `Profile` component receives
as props.

### Critical finding: profile HTML is a JS shell

`/profile/<id>` is a tiny (~12 KB) Astro/React page. There are **no `<tr>` match rows
in the static HTML.** The match table is rendered client-side by
`/_astro/Profile.AWCtGaC_.js`, which itself just calls two `fetch()` URLs:

```js
fetch(`https://mtgeloproject.net/api/players/${w}/events`)
fetch(`https://mtgeloproject.net/api/players/${w}/matches`)
```

That means HTML-scraping the profile page returns ~nothing. We must hit the JSON
endpoints. (Confirmed by running `httpx.get` server-side with our existing `Fetcher`
— both endpoints return plain JSON with no auth, no CSRF, no JS rendering needed.)

The summary stats Astro embeds inline as props (record, current_rating, ranking,
nakamura_number, **`best_event`**) are nice-to-have but not load-bearing — we get
everything richer from `/api/.../matches`.

## Sample player chosen

**Christoffer Larsen** — `https://mtgeloproject.net/profile/wrr61zbv` (linked from the
home page as the current #1, made PT SOS finals). Cross-checked against **Nathan
Steuer** (`zz14clya`, PT SOS winner) for consistency.

## Per-match data shape on profile pages

The `/api/players/<id>/matches` endpoint returns a JSON object keyed by event code.
Each value is a list of match objects.

### Example: one PT Strixhaven match (Larsen's finals)

```json
{
  "match_id": 4015653,
  "round": "F",
  "table": 1,
  "format": "standard",
  "result": "Lost 2-3",
  "own_elo": {
    "start": 2361.56,
    "end": 2339.86
  },
  "opp_data": {
    "id": "zz14clya",
    "opp": "Steuer, Nathan",
    "start": 2156.17
  }
}
```

Fields present (all checks pass):

- [x] **Round number** — `match["round"]`. Swiss rounds are stringified ints
  (`"1"`–`"15"`); top-cut rounds are `"Q"` (quarter), `"S"` (semi), `"F"` (final).
  At PT SOS, Larsen's swiss went `"1"`..`"15"` then `"Q"`, `"S"`, `"F"`.
- [x] **Format tag** — `match["format"]`. Observed values: `"draft"`, `"standard"`,
  `"sealed"`. PT SOS rounds 1–3 + 9–11 are `"draft"`, the rest `"standard"`.
- [x] **Opponent name** — `match["opp_data"]["opp"]` (e.g., `"Steuer, Nathan"` —
  `Last, First` order). **Opponent profile ID** is `match["opp_data"]["id"]`, so we
  can link match rows to opponent profiles without a second name lookup.
- [x] **Match result** — `match["result"]` is a single string like `"Won 2-0"`,
  `"Lost 0-2"`, `"Draw 1-1"`. Both the W/L/D and the game score are bundled.
- [x] **Game score** — embedded in `result` (split on space).
- [x] **Player Elo before match** — `match["own_elo"]["start"]`.
- [x] **Elo Δ** — derived as `own_elo.end - own_elo.start`. Also `own_elo.end` is
  the player's rating after the match, which is the next match's `start` (verified
  by tracing Larsen's chain). **Conservation of Elo confirmed**: in the finals,
  Larsen's Δ was −21.70 and Steuer's was +21.70. The two players' independently
  fetched `match_id=4015653` records agree on opponent ID, start Elos, and result.

Other useful fields: `match_id` (stable int, can be used to dedupe across the
two-sided fetch), `table` (table number that round).

## How to identify PT Strixhaven matches specifically

**Trivially**: the top-level key in the matches JSON is the event code, and PT
Secrets of Strixhaven is **`ptsos`**.

```python
matches = json.loads(fetcher.get(f"https://mtgeloproject.net/api/players/{pid}/matches"))
ptsos_matches = matches.get("ptsos", [])
```

Verified independently three ways:

1. Larsen's `info.best_event` (embedded in profile HTML props) is `"ptsos"` —
   internal label.
2. Larsen has exactly 18 `ptsos` matches; Steuer has 19 (winner played one more
   top-cut round). Both end with `round=="F"` opposing each other on `match_id=4015653`.
3. The search results page lists "Larsen, Christoffer" with `last event = ptsos`.

The event code is stable inside this system (also confirmed by `/api/players/<id>/events`,
which has a `code: "ptsos"` row with metadata).

## Player lookup: resolving 325 names to IDs

For our 325 PT SOS players we need to go name → `player_id`. Two practical paths:

1. **Direct redirect** — `GET /search/<LastName>/<FirstName>` with an exact match
   redirects (200) to the player's profile page. The resulting HTML contains the
   player's ID in the `Profile` astro-island's `props` attribute (`playerid` field).
   This worked for `Steuer/Nathan` → `zz14clya` on first try.
2. **Disambiguation page** — when multiple players share a surname (e.g.,
   `/search/Larsen/*` returns ~79 candidates), the HTML contains a table with
   columns `name | rating | last event` and **`<a href="/profile/<id>">` links per
   row**. The `last event` column is a strong hint: a candidate whose last event is
   `ptsos` is almost certainly the PT competitor we want.

There is also a JS combobox/autocomplete in the header (see `/_astro/Search.Cy44HT0L.js`
and `/_astro/MobileMenu.D_j8CVtT.js`), but the server-side `/search/<l>/<f>` route
is sufficient and simpler — we do not need autocomplete.

Edge cases observed:

- `/search/Smith/*` → "Your search for Smith, % returned too many results. Please
  be more specific." (so we always need at least a first initial for very common
  names — fine for our cohort).
- `/search/Zzzzqqqxx/*` → "Your search did not return any results." (graceful).

## CSS / DOM strategy for Task 7

Given the JSON-API finding, Task 7's parser does **not** need DOM selectors. It needs:

1. **Name → ID resolver** (`mtg_scrape/players_mtgelo.py` or similar):
   - Fetch `/search/<last>/<first>`.
   - If the HTML's `<title>` is `MTG Elo Project - <First> <Last>` AND the page
     contains exactly one `<astro-island ... component-url="/_astro/Profile...">`,
     it's an auto-redirect — extract the `playerid` value from the island's
     `props` attribute (it's HTML-entity-escaped JSON; decode then regex / json-load).
   - Otherwise the page is a disambiguation table — parse `<a href="/profile/...">`
     rows and prefer the one whose adjacent "last event" cell text contains `ptsos`.
     Fall back to manual mapping if still ambiguous (we'll handle this in code).
2. **Match fetcher**:
   - `GET /api/players/<id>/matches` (already cacheable via our `Fetcher`).
   - `json.loads(...)["ptsos"]` to get the list of match dicts.
   - Map each dict to a row: `(player_id, player_name, match_id, round, table,
     format, result_str, result_wld, game_wins, game_losses, elo_start, elo_end,
     elo_delta, opp_id, opp_name, opp_elo_start)`.
3. **Result string parsing**: `result.split()` → `("Won"|"Lost"|"Draw", "2-1")`,
   then split the score on `"-"` for game-level wins/losses.

Selectors needed: none for matches; for the search disambiguation HTML the parser
needs:

- `<title>` tag (to detect auto-redirect).
- Regex on `astro-island ... props="{...playerid... <id> ...}"` OR an HTML parser
  pulling the `<astro-island>` element with `component-url` containing
  `/_astro/Profile`.
- For multi-result pages: `<a href="/profile/<id>">` anchors inside `<main>`, with
  their following sibling cells for `rating` and `last event`. Selectolax / lxml
  with a CSS selector like `main a[href^='/profile/']` plus walking the row.

## Fixtures captured

In `tests/fixtures/mtgelo/` (sizes confirm they have real content):

| File | Size | Purpose |
| --- | --- | --- |
| `home.html` | 12 KB | URL scheme + search form |
| `faq.html` | 49 KB | data provenance, event coverage |
| `leaders-all.html` | 88 KB | confirms `/profile/<id>` slugs + `#<eventcode>` anchors |
| `sample-player-larsen.html` | 12 KB | proves profile HTML is a JS shell (Christoffer Larsen, finals of PT SOS) |
| `profile-bundle.js` | 43 KB | source of the two `/api/players/...` endpoints |
| `search-bundle.js` | 0.9 KB | URL pattern `/search/<last>/<first>` |
| `mobilemenu-bundle.js` | 51 KB | combobox internals (unused; for completeness) |
| `search-results-steuer.html` | 12 KB | exact-match auto-redirect (Nathan Steuer → `zz14clya`) |
| `search-results-larsen.html` | 18.8 KB **main region** | multi-result disambiguation table with `last event` column |
| `search-results-smith.html` | 10 KB | "too many results" error state |
| `search-results-noone.html` | 10 KB | "no results" error state |
| `api-events-larsen.json` | 26 KB | per-event metadata (date, format, type, etc.) for one player |
| `api-matches-larsen.json` | 240 KB | the load-bearing fixture — match-level data including `ptsos` |
| `api-matches-steuer.json` | (PT SOS winner) cross-check matches; confirms Elo conservation |

## Plan revisions implied for downstream tasks

- **Task 6 (name → ID resolver)**: simpler than expected — single HTTP GET per name
  to `/search/<last>/<first>`, parse one `<astro-island>` or a small table. No
  Playwright, no JS execution.
- **Task 7 (match parser)**: should be renamed in spirit from "HTML match table
  parser" to **"JSON matches API client"**. Implementation is `json.loads(...)["ptsos"]`
  + dataclass mapping. No DOM selectors needed.
- **Schema for `data/matches.csv`**: can include richer fields than originally
  planned (opp_id, exact pre/post Elo to 2 decimals, table number, format tag per
  match, etc.).
- **Caching**: existing `Fetcher` works as-is for the JSON endpoints — it's just
  text. Fixture files for tests can be the captured JSON.

## Things that surprised me

- The site is much more API-friendly than the spec assumed. There's effectively a
  public REST API with no auth.
- `best_event: "ptsos"` is embedded in the profile HTML props, so we can even
  pre-filter "this player has PT SOS as their best event" without fetching matches
  — though we shouldn't rely on it (the player's best event might be elsewhere).
- The data is internally consistent at the match level (Elo conservation,
  symmetric opponent IDs). That's reassuring for downstream analysis.
- Round labels use single-letter codes for top cut (`Q`/`S`/`F`), not numbers like
  16/17/18 — parser must treat `round` as a string, not an int.
- Larsen has 18 ptsos matches but Steuer has 19 (Steuer played QF, Larsen received
  a bye into SF as the higher seed — typical PT structure). Counts per player will
  not be uniform; this is fine but worth flagging for any "did we get all rounds"
  check.

## Decision (repeated for clarity)

- [x] **PROCEED** with mtgeloproject as the Elo data source — all required fields
      present, accessed via a clean JSON API.
- [ ] PIVOT to Playwright-melee — not needed.
- [ ] PARTIAL — not applicable.

Caveat for the planner: Tasks 6 and 7 should be updated to reflect that we're
hitting `/api/players/<id>/matches` directly rather than parsing rendered match
tables. The spec stays roughly the same; the implementation is simpler.
