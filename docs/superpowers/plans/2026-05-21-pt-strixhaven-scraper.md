# PT Secrets of Strixhaven Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python pipeline that scrapes magic.gg (decklists + archetypes) and mtgeloproject.net (round-by-round matches + Elo) for Pro Tour Secrets of Strixhaven (Las Vegas, May 1–3 2026), joins them on player name, and emits a constructed-only matchups dataset for downstream analysis.

**Architecture:** Two independent scrapers feeding a joiner, sharing a small cached HTTP fetcher. Outputs are CSVs in `data/`; raw HTML lives in `cache/` (gitignored). Each parser is TDD'd against saved HTML fixtures so tests don't depend on the live sites.

**Tech Stack:** Python 3.11+, `httpx` (sync), `beautifulsoup4`, `pandas`, `pytest`. Environment managed with `uv`.

**Source of truth:** `docs/superpowers/specs/2026-05-21-pt-strixhaven-scraper-design.md`

---

## Task 1: Project scaffolding

Get a runnable Python project skeleton in place with the right dependencies, directory layout, and one passing smoke test.

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `mtg_scrape/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_smoke.py`
- Create: `data/.gitkeep`, `tests/fixtures/.gitkeep`, `notebooks/.gitkeep` (not `cache/.gitkeep` — `cache/` is gitignored; `fetch.py` mkdirs it at runtime)
- Modify: `.gitignore` (append python build entries)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "mtg-pt-data-exploration"
version = "0.1.0"
description = "Scrape and analyze PT Secrets of Strixhaven match + deck data"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "pandas>=2.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["mtg_scrape"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Set up env and install deps**

Run: `cd /home/tal/Documents/mtg-pt-data-exploration && uv venv && uv pip install -e ".[dev]"`

Expected: virtualenv created at `.venv/`, dependencies installed, no errors.

- [ ] **Step 3: Update `.gitignore`**

The current `.gitignore` already covers `cache/`, `__pycache__/`, `*.pyc`, `.venv/`, `.ipynb_checkpoints/`. Append:

```
# python build
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
```

- [ ] **Step 4: Write smoke test**

Create `tests/test_smoke.py`:

```python
def test_package_importable():
    import mtg_scrape  # noqa: F401
```

- [ ] **Step 5: Run smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 6: Write minimal README**

Create `README.md`:

```markdown
# mtg-pt-data-exploration

Scrape and analyze Pro Tour Secrets of Strixhaven (Las Vegas, May 2026) match + deck data.

## Setup

```
uv venv
uv pip install -e ".[dev]"
```

## Pipeline

1. `python -m mtg_scrape.decks_magicgg`   # writes data/decks.csv
2. `python -m mtg_scrape.matches_mtgelo`  # writes data/matches.csv
3. `python -m mtg_scrape.build_matchups`  # writes data/matchups.csv, data/players.csv

See `docs/superpowers/specs/2026-05-21-pt-strixhaven-scraper-design.md` for design.
```

- [ ] **Step 7: Create empty directories with .gitkeep**

Run:
```
mkdir -p data cache tests/fixtures notebooks
touch data/.gitkeep tests/fixtures/.gitkeep notebooks/.gitkeep
```

`cache/` is gitignored; `fetch.py` will mkdir it at runtime.

- [ ] **Step 8: Commit**

```
git add pyproject.toml README.md mtg_scrape/ tests/ data/.gitkeep tests/fixtures/.gitkeep notebooks/.gitkeep .gitignore
git commit -m "Scaffold mtg-pt-data-exploration project"
```

---

## Task 2: HTTP fetcher with on-disk cache and rate limiting

`fetch.py` is the foundation for both scrapers. It must: cache responses to disk keyed by URL hash, rate-limit to ~1 req/sec, and retry on transient errors. TDD it because it's the one piece of plumbing both downstream modules depend on.

**Files:**
- Create: `mtg_scrape/fetch.py`
- Create: `tests/test_fetch.py`

- [ ] **Step 1: Write failing test for cache hit short-circuits network**

Create `tests/test_fetch.py`:

```python
from pathlib import Path
import httpx
import pytest
from mtg_scrape.fetch import Fetcher


def test_cache_hit_skips_network(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/foo"
    # Pre-populate cache
    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0)
    cache_path = fetcher._cache_path_for(url)
    cache_path.write_text("<html>cached</html>", encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("network should not be called on cache hit")

    monkeypatch.setattr(httpx, "get", boom)

    assert fetcher.get(url) == "<html>cached</html>"


def test_miss_calls_network_and_writes_cache(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    url = "https://example.com/bar"

    calls = []

    class FakeResp:
        status_code = 200
        text = "<html>fresh</html>"
        def raise_for_status(self): pass

    def fake_get(u, **kwargs):
        calls.append(u)
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0)
    result = fetcher.get(url)

    assert result == "<html>fresh</html>"
    assert calls == [url]
    assert fetcher._cache_path_for(url).read_text(encoding="utf-8") == "<html>fresh</html>"


def test_rate_limit_sleeps_between_calls(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FakeResp:
        status_code = 200
        text = "ok"
        def raise_for_status(self): pass

    monkeypatch.setattr(httpx, "get", lambda u, **k: FakeResp())

    sleeps = []
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("mtg_scrape.fetch.time.monotonic", lambda: next(clock))
    clock = iter([0.0, 0.0, 0.2, 0.2])  # second call 0.2s after first

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=1.0)
    fetcher.get("https://example.com/a")
    fetcher.get("https://example.com/b")

    # First call: no sleep (no prior request). Second call: sleeps ~0.8s.
    assert len(sleeps) == 1
    assert 0.7 < sleeps[0] <= 1.0


def test_retry_then_success(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FlakyResp:
        def __init__(self, status):
            self.status_code = status
            self.text = "ok"
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

    seq = iter([FlakyResp(503), FlakyResp(200)])
    monkeypatch.setattr(httpx, "get", lambda u, **k: next(seq))
    monkeypatch.setattr("mtg_scrape.fetch.time.sleep", lambda s: None)

    fetcher = Fetcher(cache_dir=cache_dir, min_interval_s=0.0, max_retries=3)
    assert fetcher.get("https://example.com/flaky") == "ok"
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mtg_scrape.fetch'`.

- [ ] **Step 3: Implement `mtg_scrape/fetch.py`**

```python
"""HTTP GET with on-disk cache and polite rate limiting."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

_DEFAULT_HEADERS = {
    "User-Agent": "mtg-pt-data-exploration/0.1 (personal data exploration; contact: github.com/talf301)",
}


@dataclass
class Fetcher:
    cache_dir: Path
    min_interval_s: float = 1.0
    max_retries: int = 3
    timeout_s: float = 30.0
    _last_request_at: float | None = None  # monotonic timestamp; None = no prior request

    def _cache_path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def get(self, url: str) -> str:
        cache_path = self._cache_path_for(url)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        # Rate-limit: sleep until min_interval_s has elapsed since last request.
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = httpx.get(url, headers=_DEFAULT_HEADERS, timeout=self.timeout_s, follow_redirects=True)
                resp.raise_for_status()
                self._last_request_at = time.monotonic()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(resp.text, encoding="utf-8")
                return resp.text
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                backoff = 2 ** attempt
                time.sleep(backoff)

        assert last_exc is not None
        raise last_exc
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/fetch.py tests/test_fetch.py
git commit -m "Add cached, rate-limited HTTP fetcher"
```

---

## Task 3: Capture magic.gg fixtures and verify URL structure

Fetch one real magic.gg decklist page (live, into the cache) and freeze a copy under `tests/fixtures/magicgg/` so the parser tests in Task 4 can run offline. Also confirm the URL suffix list (a-f, m-r, s-z) is correct — the actual splits may differ.

**Files:**
- Create: `scripts/snapshot_magicgg.py` (one-shot helper, kept in repo for reproducibility)
- Create: `tests/fixtures/magicgg/decklists-a-f.html`
- Create: `tests/fixtures/magicgg/decklists-m-r.html` (if URL exists)
- Create: `tests/fixtures/magicgg/decklists-s-z.html` (if URL exists)
- Possibly Create: additional fixtures for whatever surname buckets actually exist (e.g. g-l)

- [ ] **Step 1: Write the snapshot helper**

Create `scripts/snapshot_magicgg.py`:

```python
"""Fetch magic.gg PT Strixhaven decklist pages and freeze them as test fixtures.

Run once. Re-run only if you need to refresh fixtures.
"""
from pathlib import Path
from mtg_scrape.fetch import Fetcher

CANDIDATE_SUFFIXES = ["a-f", "g-l", "m-r", "s-z"]  # try each; the live site uses some subset
BASE = "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-{suffix}"

if __name__ == "__main__":
    root = Path(__file__).parent.parent
    cache = root / "cache"
    fixtures = root / "tests" / "fixtures" / "magicgg"
    fixtures.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(cache_dir=cache, min_interval_s=1.0)

    for suffix in CANDIDATE_SUFFIXES:
        url = BASE.format(suffix=suffix)
        try:
            html = fetcher.get(url)
        except Exception as exc:
            print(f"SKIP {suffix}: {exc}")
            continue
        target = fixtures / f"decklists-{suffix}.html"
        target.write_text(html, encoding="utf-8")
        print(f"OK   {suffix} -> {target}")
```

- [ ] **Step 2: Run the snapshot helper**

Run: `.venv/bin/python scripts/snapshot_magicgg.py`
Expected: at least 2-3 of the candidate suffixes succeed; the rest print SKIP. The actual surviving suffixes are the canonical list — note them in a comment in `mtg_scrape/decks_magicgg.py` later.

- [ ] **Step 3: Sanity-check a fixture**

Run: `head -c 2000 tests/fixtures/magicgg/decklists-a-f.html | grep -E '(class=|<h[1-3])' | head -20` (or open in editor).

Confirm by eye: the page contains player names and decklists. Identify the recurring HTML pattern that holds one decklist (likely a `<div class="..."><h3>Player Name</h3>...<ul><li>4 Card Name</li>...</ul></div>` or similar). Write down the actual selectors as a comment in Task 4.

- [ ] **Step 4: Commit fixtures + script**

```
git add scripts/snapshot_magicgg.py tests/fixtures/magicgg/
git commit -m "Freeze magic.gg decklist pages as test fixtures"
```

---

## Task 4: magic.gg decklist parser (TDD against fixture)

Parse a saved magic.gg page into `(player_name, archetype_magicgg, mainboard, sideboard)` tuples. TDD'd against the fixture from Task 3.

**Files:**
- Create: `mtg_scrape/decks_magicgg.py` (parser + scraper orchestrator)
- Create: `tests/test_decks_magicgg.py`

- [ ] **Step 1: Write failing test for parser**

Create `tests/test_decks_magicgg.py`:

```python
from pathlib import Path
from mtg_scrape.decks_magicgg import parse_decklist_page

FIXTURE = Path(__file__).parent / "fixtures" / "magicgg" / "decklists-a-f.html"


def test_parses_at_least_one_decklist():
    html = FIXTURE.read_text(encoding="utf-8")
    decks = parse_decklist_page(html)
    assert len(decks) > 0
    first = decks[0]
    assert first.player_name and isinstance(first.player_name, str)
    assert first.archetype_magicgg and isinstance(first.archetype_magicgg, str)
    assert first.mainboard, "mainboard should be non-empty list"


def test_mainboard_cards_have_qty_and_name():
    html = FIXTURE.read_text(encoding="utf-8")
    decks = parse_decklist_page(html)
    qty, name = decks[0].mainboard[0]
    assert isinstance(qty, int) and qty > 0
    assert isinstance(name, str) and name


def test_mainboard_total_is_60_for_standard():
    html = FIXTURE.read_text(encoding="utf-8")
    decks = parse_decklist_page(html)
    for d in decks:
        total = sum(qty for qty, _ in d.mainboard)
        # Some decks legally have 61+ main; Standard minimum is 60
        assert total >= 60, f"{d.player_name} mainboard total {total} < 60"


def test_sideboard_total_is_at_most_15():
    html = FIXTURE.read_text(encoding="utf-8")
    decks = parse_decklist_page(html)
    for d in decks:
        total = sum(qty for qty, _ in d.sideboard)
        assert total <= 15, f"{d.player_name} sideboard total {total} > 15"
```

- [ ] **Step 2: Run test, confirm fails**

Run: `.venv/bin/pytest tests/test_decks_magicgg.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `mtg_scrape/decks_magicgg.py`**

The exact selectors depend on what you saw in Task 3 step 3. The skeleton below is the shape; fill in the BeautifulSoup selectors against the real page.

```python
"""Parse magic.gg's PT Secrets of Strixhaven Standard decklist pages.

Surname buckets actually present on magic.gg are noted in URLS below.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from mtg_scrape.fetch import Fetcher

# Confirmed during Task 3 snapshot run; update if magic.gg's URL scheme changes.
URLS = [
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-a-f",
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-m-r",
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-s-z",
    # add g-l etc. if Task 3 found them
]


@dataclass
class Deck:
    player_name: str
    archetype_magicgg: str
    mainboard: list[tuple[int, str]] = field(default_factory=list)
    sideboard: list[tuple[int, str]] = field(default_factory=list)


def parse_decklist_page(html: str) -> list[Deck]:
    """Parse one magic.gg decklist bucket page into Deck records."""
    soup = BeautifulSoup(html, "lxml")
    decks: list[Deck] = []

    # NOTE: Replace these selectors with the actual structure observed in
    # tests/fixtures/magicgg/decklists-a-f.html. The patterns below are a
    # plausible default; verify against fixture.
    for block in soup.select("div.decklist, article.decklist, section.deck"):
        name_el = block.select_one("h3, .player-name, .decklist-header")
        arch_el = block.select_one(".archetype, .deck-name, h4")
        main_lis = block.select(".mainboard li, ul.mainboard li")
        side_lis = block.select(".sideboard li, ul.sideboard li")

        if not name_el or not main_lis:
            continue

        deck = Deck(
            player_name=name_el.get_text(strip=True),
            archetype_magicgg=(arch_el.get_text(strip=True) if arch_el else ""),
        )
        for li in main_lis:
            deck.mainboard.append(_parse_card_line(li.get_text(strip=True)))
        for li in side_lis:
            deck.sideboard.append(_parse_card_line(li.get_text(strip=True)))
        decks.append(deck)

    return decks


def _parse_card_line(text: str) -> tuple[int, str]:
    """'4 Llanowar Elves' -> (4, 'Llanowar Elves')."""
    qty_str, _, name = text.partition(" ")
    return int(qty_str), name.strip()


def _serialize_cards(cards: list[tuple[int, str]]) -> str:
    return "; ".join(f"{q} {n}" for q, n in cards)


def scrape_all(fetcher: Fetcher) -> list[Deck]:
    all_decks: list[Deck] = []
    for url in URLS:
        html = fetcher.get(url)
        all_decks.extend(parse_decklist_page(html))
    return all_decks


def write_csv(decks: list[Deck], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["player_name", "archetype_magicgg", "mainboard", "sideboard"])
        for d in decks:
            w.writerow([d.player_name, d.archetype_magicgg, _serialize_cards(d.mainboard), _serialize_cards(d.sideboard)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--out", default="data/decks.csv")
    args = parser.parse_args()

    fetcher = Fetcher(cache_dir=Path(args.cache_dir), min_interval_s=1.0)
    decks = scrape_all(fetcher)
    write_csv(decks, Path(args.out))
    print(f"Wrote {len(decks)} decklists to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Iterate on selectors until tests pass**

Run: `.venv/bin/pytest tests/test_decks_magicgg.py -v`

If failing with 0 decks parsed, open `tests/fixtures/magicgg/decklists-a-f.html` in an editor and read the actual HTML structure surrounding a deck. Update the CSS selectors in `parse_decklist_page` to match. Re-run. Repeat until the four assertions pass.

Expected end state: 4 passed.

- [ ] **Step 5: Run the scraper end-to-end against the live cache**

Run: `.venv/bin/python -m mtg_scrape.decks_magicgg`
Expected: prints `Wrote N decklists to data/decks.csv` where N ≈ 325.

Open `data/decks.csv` and visually confirm:
- Row count is close to 325.
- `archetype_magicgg` column is mostly non-empty.
- `mainboard` column contains card list strings.

- [ ] **Step 6: Commit**

```
git add mtg_scrape/decks_magicgg.py tests/test_decks_magicgg.py data/decks.csv
git commit -m "Add magic.gg decklist scraper"
```

---

## Task 5: mtgeloproject verification spike

Confirm — *before* writing a parser — that mtgeloproject.net actually exposes (a) a name-search → player-profile flow, (b) per-match Elo + Δ on profile pages, (c) format/round metadata sufficient to filter to PT Strixhaven matches. If any of these fail, the matches half of the plan needs to pivot to Playwright-against-melee and this plan must be revised before proceeding.

**Files:**
- Create: `scripts/snapshot_mtgelo.py`
- Create: `tests/fixtures/mtgelo/home.html`
- Create: `tests/fixtures/mtgelo/sample-player.html` (one well-known player who played PT Strixhaven, e.g. "Nathan Steuer" who won the event)
- Create: `tests/fixtures/mtgelo/search-results.html` (search response page)
- Create: `docs/superpowers/spike-notes/2026-05-21-mtgelo-spike.md`

- [ ] **Step 1: Write the snapshot helper**

Create `scripts/snapshot_mtgelo.py`:

```python
"""Spike: fetch a few representative mtgeloproject pages and freeze them.

We need to confirm:
 - URL pattern for searching by player name
 - URL pattern for a player profile
 - Per-match data shape (round, format, opponent, result, Elo, Δ)
 - How to identify which matches belong to PT Secrets of Strixhaven
"""
from pathlib import Path
from mtg_scrape.fetch import Fetcher

if __name__ == "__main__":
    root = Path(__file__).parent.parent
    fetcher = Fetcher(cache_dir=root / "cache", min_interval_s=1.0)
    fixtures = root / "tests" / "fixtures" / "mtgelo"
    fixtures.mkdir(parents=True, exist_ok=True)

    targets = {
        "home.html": "https://mtgeloproject.net/",
        # Tweak these once you've inspected home.html and seen what URLs the
        # site actually uses. Common patterns to try:
        "search-results.html": "https://mtgeloproject.net/search?name=Nathan+Steuer",
        # If a known player ID is visible from search results, fetch that profile:
        # "sample-player.html": "https://mtgeloproject.net/player/<ID>",
    }
    for fname, url in targets.items():
        try:
            html = fetcher.get(url)
            (fixtures / fname).write_text(html, encoding="utf-8")
            print(f"OK   {fname} <- {url}")
        except Exception as exc:
            print(f"FAIL {fname} <- {url}: {exc}")
```

- [ ] **Step 2: Run the spike (iteratively)**

Run: `.venv/bin/python scripts/snapshot_mtgelo.py`

Then open `tests/fixtures/mtgelo/home.html` and find: the search form (its action URL and parameter name), navigation to events, navigation to players. Update the `targets` dict in `snapshot_mtgelo.py` with the correct URLs, re-run.

Iterate until you have:
- `home.html`
- `search-results.html` for a real player name
- `sample-player.html` for that player's profile, showing their PT Strixhaven match history

- [ ] **Step 3: Confirm or pivot — record findings**

Open the sample player's profile HTML and check by hand. Create `docs/superpowers/spike-notes/2026-05-21-mtgelo-spike.md`:

```markdown
# mtgeloproject spike — findings (2026-05-21)

## URL patterns
- Home: https://mtgeloproject.net/
- Search: <fill in>
- Player profile: <fill in>

## Per-match data shape on profile pages
Sample row (paste a real fragment of the match table HTML here):

```
<paste here>
```

Fields present:
- [ ] Round number
- [ ] Format tag (or ability to filter to PT Strixhaven somehow)
- [ ] Opponent name (linked to opponent's profile)
- [ ] Match result (W/L/D)
- [ ] Game score (2-1 etc.)  — yes / no
- [ ] Player Elo before match — yes / no
- [ ] Elo Δ from match — yes / no

## How to identify PT Strixhaven matches specifically
<describe: event id? date range? event name in a column?>

## Decision
- [ ] Proceed with mtgeloproject scraper (Task 6)
- [ ] PIVOT to Playwright-melee — STOP HERE and revise the plan
```

Fill in the answers honestly. If any of "Player Elo before match" / "Elo Δ" / "Round number" is missing, that's a pivot signal.

- [ ] **Step 4: Decision gate**

If the spike notes confirm everything we need, continue to Task 6.
If not, STOP. Open the spec and amend the matches source. Do not write Task 6 code against assumptions that don't hold.

- [ ] **Step 5: Commit spike artifacts**

```
git add scripts/snapshot_mtgelo.py tests/fixtures/mtgelo/ docs/superpowers/spike-notes/
git commit -m "Verify mtgeloproject exposes per-match Elo data"
```

---

## Task 6: name normalization

Small utility module that normalizes player names and applies a manual override map. Used by both the matches scraper (to resolve magic.gg names to mtgeloproject names) and the joiner (to detect mismatches).

**Files:**
- Create: `mtg_scrape/names.py`
- Create: `tests/test_names.py`
- Create: `data/name_overrides.csv` (with header only, no rows initially)

- [ ] **Step 1: Write failing tests**

Create `tests/test_names.py`:

```python
from pathlib import Path
import csv
import pytest
from mtg_scrape.names import normalize, build_resolver, load_overrides


def test_normalize_lowercases_and_strips():
    assert normalize("  Nathan Steuer  ") == "nathan steuer"


def test_normalize_folds_accents():
    assert normalize("Javier Domínguez") == "javier dominguez"


def test_normalize_collapses_whitespace():
    assert normalize("Marcio   Carvalho") == "marcio carvalho"


def test_normalize_swaps_last_comma_first():
    # mtgeloproject's API returns opponent names in "Last, First" order;
    # magic.gg lists "First Last". Normalize should fold both to the same form.
    assert normalize("Steuer, Nathan") == "nathan steuer"
    assert normalize("Domínguez, Javier") == "javier dominguez"


def test_normalize_leaves_uncomma_names_alone():
    assert normalize("Nathan Steuer") == "nathan steuer"


def test_resolver_matches_canonical_by_normalized_name():
    # magic.gg has these canonical names. Inputs may differ only in accents/case.
    resolver = build_resolver(
        canonical_names=["Nathan Steuer", "Javier Domínguez"],
        overrides={},
    )
    assert resolver("nathan steuer") == "Nathan Steuer"
    assert resolver("Javier Dominguez") == "Javier Domínguez"  # accent-insensitive


def test_resolver_uses_override_for_substantial_name_differences():
    # magic.gg lists "Sam Black"; mtgeloproject lists "Samuel Black".
    # An override row in the CSV is (magic_gg_name="Sam Black", mtgelo_name="Samuel Black");
    # load_overrides normalizes both sides and stores {mtgelo_norm: magic_gg_norm}.
    resolver = build_resolver(
        canonical_names=["Sam Black"],
        overrides={"samuel black": "sam black"},
    )
    assert resolver("Samuel Black") == "Sam Black"


def test_resolver_returns_none_when_unresolvable():
    resolver = build_resolver(canonical_names=["Nathan Steuer"], overrides={})
    assert resolver("Unknown Player") is None


def test_load_overrides_maps_mtgelo_to_magicgg_normalized(tmp_path: Path):
    p = tmp_path / "overrides.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["magic_gg_name", "mtgelo_name"])
        w.writerow(["Sam Black", "Samuel Black"])
    # Keys are normalized mtgelo names; values are normalized magic.gg names.
    assert load_overrides(p) == {"samuel black": "sam black"}
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_names.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `mtg_scrape/names.py`**

```python
"""Normalize player names and resolve cross-source mismatches.

magic.gg and mtgeloproject sometimes spell the same player slightly differently
(accents, full vs short name). `normalize` does cheap case/accent/whitespace
folding; `build_resolver` returns a lookup function from any spelling to a
canonical magic.gg name.
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Callable, Iterable


def normalize(name: str) -> str:
    """Fold case, swap "Last, First" -> "First Last", strip accents, collapse whitespace.

    mtgeloproject's JSON returns opponent names as "Last, First". magic.gg uses
    "First Last". Both must normalize to the same form for cross-source joins.
    """
    if name is None:
        return ""
    # "Last, First" -> "First Last" (only one comma, both halves non-empty)
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            name = f"{parts[1]} {parts[0]}"
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(no_accents.lower().split())


def load_overrides(path: Path) -> dict[str, str]:
    """Load overrides CSV. Returns dict mapping normalized mtgelo name to normalized magic.gg name.

    CSV format:  magic_gg_name, mtgelo_name
    """
    overrides: dict[str, str] = {}
    if not path.exists():
        return overrides
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            magic_gg_norm = normalize(row["magic_gg_name"])
            mtgelo_norm = normalize(row["mtgelo_name"])
            overrides[mtgelo_norm] = magic_gg_norm
    return overrides


def build_resolver(
    canonical_names: Iterable[str],
    overrides: dict[str, str],
) -> Callable[[str], str | None]:
    """Return a function: any-spelling -> canonical magic.gg spelling, or None.

    Lookup strategy:
      1. Accent/case/whitespace-folded direct match against canonical_names.
      2. Override lookup: if the input normalizes to an override key,
         fetch the corresponding normalized magic.gg name and resolve that.
    """
    canonical_by_norm = {normalize(n): n for n in canonical_names}

    def resolve(name: str) -> str | None:
        n = normalize(name)
        if n in canonical_by_norm:
            return canonical_by_norm[n]
        if n in overrides:
            magic_gg_norm = overrides[n]
            if magic_gg_norm in canonical_by_norm:
                return canonical_by_norm[magic_gg_norm]
        return None

    return resolve
```

- [ ] **Step 4: Create empty overrides CSV**

Create `data/name_overrides.csv`:

```csv
magic_gg_name,mtgelo_name
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `.venv/bin/pytest tests/test_names.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```
git add mtg_scrape/names.py tests/test_names.py data/name_overrides.csv
git commit -m "Add name normalization and override resolver"
```

---

## Task 7: mtgeloproject matches JSON parser (TDD against fixture)

**Revised after the Task 5 spike.** mtgeloproject exposes a clean JSON API at `/api/players/<id>/matches` that returns match data keyed by event code. PT Secrets of Strixhaven's event code is `"ptsos"`. We parse that JSON directly rather than scraping rendered HTML.

**Files:**
- Create: `mtg_scrape/matches_mtgelo.py` (parser + dataclass; orchestrator in Task 8)
- Create: `tests/test_matches_mtgelo.py`

The JSON shape for one match record (verbatim from the spike):

```json
{
  "match_id": 4015653,
  "round": "F",
  "table": 1,
  "format": "standard",
  "result": "Lost 2-3",
  "own_elo": {"start": 2361.56, "end": 2339.86},
  "opp_data": {"id": "zz14clya", "opp": "Steuer, Nathan", "start": 2156.17}
}
```

Top-level structure: `{"ptsos": [match, match, ...], "<other_event>": [...], ...}`. `round` is a string — swiss rounds are stringified ints (`"1"`–`"15"`); top cut uses `"Q"`, `"S"`, `"F"`. `format` is lowercase (`"standard"`, `"draft"`, `"sealed"`). `result` is a single string combining outcome and game score, like `"Won 2-1"`, `"Lost 0-2"`, `"Draw 1-1"`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_matches_mtgelo.py`:

```python
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
    # All 18 should be ptsos; event_code is captured on each row
    assert all(m.event_code == EVENT_CODE for m in matches)


def test_round_remains_string():
    """Round must NOT be coerced to int; top cut uses Q/S/F."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    rounds = {m.round for m in matches}
    # Larsen's run: rounds "1"..."15" then "S" and "F" (he got a bye into SF as #2 seed).
    assert "F" in rounds
    assert "S" in rounds
    assert "1" in rounds  # as string, not int


def test_result_parsing_split():
    """'Lost 2-3' should split to result='L', game_score='2-3'."""
    matches = parse_matches_json(
        FIXTURE.read_text(encoding="utf-8"), player_name=LARSEN_NAME, player_id=LARSEN_ID
    )
    # Find any result we know maps cleanly
    wins = [m for m in matches if m.result == "W"]
    losses = [m for m in matches if m.result == "L"]
    assert wins, "should have some wins"
    assert losses, "should have some losses"
    # Each game_score should be of the form N-N
    for m in matches:
        a, b = m.game_score.split("-")
        assert a.isdigit() and b.isdigit()
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mtg_scrape.matches_mtgelo'`.

- [ ] **Step 3: Implement parser portion of `mtg_scrape/matches_mtgelo.py`**

```python
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
    player_id: str          # mtgeloproject player slug, e.g. "wrr61zbv"
    match_id: int           # stable global id; the dedupe key across perspectives
    round: str              # "1".."15" for swiss; "Q"/"S"/"F" for top cut
    table: int | None
    format: str             # "standard" / "draft" / "sealed"
    opponent_name: str      # raw mtgelo "Last, First" string
    opponent_id: str        # mtgeloproject opponent slug
    result: str             # "W" / "L" / "D" from player's perspective
    game_score: str         # "2-1", "0-2", etc.
    elo_pre: float          # player's own Elo before this match
    elo_post: float         # player's own Elo after this match
    elo_delta: float        # elo_post - elo_pre
    opp_elo_pre: float      # opponent's pre-match Elo, exposed in opp_data.start
    event_code: str = EVENT_CODE


def parse_matches_json(
    json_text: str,
    player_name: str,
    player_id: str,
) -> list[ProfileMatch]:
    """Parse one /api/players/<id>/matches response into ProfileMatch rows.

    Returns only matches for the PT Secrets of Strixhaven event (key 'ptsos' in the JSON).
    """
    payload = json.loads(json_text)
    raw_matches = payload.get(EVENT_CODE, [])
    rows: list[ProfileMatch] = []
    for m in raw_matches:
        result_str = m.get("result", "")
        outcome_word, _, game_score = result_str.partition(" ")
        result = _normalize_outcome(outcome_word)
        if not game_score:
            game_score = ""

        own_elo = m.get("own_elo") or {}
        opp_data = m.get("opp_data") or {}
        elo_pre = float(own_elo.get("start"))
        elo_post = float(own_elo.get("end"))

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
            opp_elo_pre=float(opp_data.get("start")) if opp_data.get("start") is not None else float("nan"),
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
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: 6 passed.

If any test fails, debug by reading the fixture (`tests/fixtures/mtgelo/api-matches-larsen.json`) and the spike notes (`docs/superpowers/spike-notes/2026-05-21-mtgelo-spike.md`). The expected values in the finals-specific test (`match_id=4015653`, opponent `Steuer, Nathan`, Elos 2361.56/2339.86) were independently verified during the spike.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/matches_mtgelo.py tests/test_matches_mtgelo.py
git commit -m "Parse mtgeloproject matches API JSON for PT Strixhaven"
```

---

## Task 8: mtgeloproject orchestrator — name → player_id, walk profiles via JSON API, dedupe by match_id

**Revised after the Task 5 spike.** Adds three pieces on top of Task 7's parser:

1. `find_player_id(fetcher, magic_gg_name)` — hits `https://mtgeloproject.net/search/<Last>/<First>` and parses the response HTML. Two response shapes:
   - **Auto-redirect / exact match:** the response IS the profile page (Fetcher follows the 30x). HTML contains a single `<astro-island ... component-url="/_astro/Profile...">` whose `props` attribute is HTML-entity-escaped JSON containing a `playerid` field.
   - **Disambiguation page:** the response is a search-results page with one or more `<a href="/profile/<id>">` links inside the main content. Each row has a "last event" cell; for PT Strixhaven players that should be `"ptsos"`. Pick that row.
2. `merge_match_perspectives` — dedupe by `match_id` (stable integer from the API) into one `MergedMatch` per match. Two perspectives → both sides' Elos populated. One perspective → other side's `elo_pre` from `opp_data.start`, other side's `elo_post`/`elo_delta` = NaN.
3. Orchestration in `main()`: read the magic.gg roster from `data/decks.csv`, resolve each name to an mtgelo player_id, fetch each player's matches JSON via the API, parse + dedupe, write `data/matches.csv`.

**Files:**
- Modify: `mtg_scrape/matches_mtgelo.py`
- Modify: `tests/test_matches_mtgelo.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_matches_mtgelo.py`:

```python
import math
from mtg_scrape.matches_mtgelo import (
    MergedMatch,
    find_player_id,
    merge_match_perspectives,
    split_name_for_search,
)

SEARCH_AUTOREDIRECT_FIXTURE = Path(__file__).parent / "fixtures" / "mtgelo" / "search-results-steuer.html"
SEARCH_DISAMBIG_FIXTURE = Path(__file__).parent / "fixtures" / "mtgelo" / "search-results-larsen.html"


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
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: ~8 new failures (existing 10 still pass).

- [ ] **Step 3: Implement the new functions and dataclass in `mtg_scrape/matches_mtgelo.py`**

Append to `mtg_scrape/matches_mtgelo.py` (keep all existing code; this is additive):

```python
import csv
import html
import json
import math
import re
from pathlib import Path
from urllib.parse import quote
from dataclasses import dataclass
from typing import Iterable, Protocol

from bs4 import BeautifulSoup

# Add at top with other imports (after the existing 'import json' from Task 7) ---
# Pre-existing imports remain; the lines above are new ones to add.


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
    the keys is `playerid`. Returns the id string or None.
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
        if isinstance(pid, str) and re.fullmatch(r"[a-z0-9]{8}", pid):
            return pid
        # Astro often wraps values as [type, value]
        if isinstance(pid, list) and len(pid) == 2 and isinstance(pid[1], str):
            return pid[1]
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
    """Look for /profile/<id> anchor whose row references the ptsos event."""
    candidates: list[tuple[str, str]] = []  # (player_id, last_event_text)
    for a in soup.select("a[href^='/profile/']"):
        href = a.get("href", "")
        m = re.match(r"/profile/([a-z0-9]{8})", href)
        if not m:
            continue
        pid = m.group(1)
        # Last-event hint: walk the enclosing row to find a cell containing
        # "ptsos". We don't assume a specific column index.
        row = a.find_parent("tr") or a.find_parent("li") or a.parent
        row_text = row.get_text(" ", strip=True).lower() if row else ""
        candidates.append((pid, row_text))

    # Prefer a row that mentions "ptsos" (most-recent-event hint).
    for pid, text in candidates:
        if "ptsos" in text:
            return pid
    # Otherwise fall back to the single unique id, if there's only one.
    unique = {pid for pid, _ in candidates}
    if len(unique) == 1:
        return unique.pop()
    return None


@dataclass
class MergedMatch:
    """One dedupe-merged match across both player perspectives.

    player_a is the side whose mtgeloproject player_id sorts lexicographically
    first; player_b is the other. Naming side: if we fetched that player, the
    canonical magic.gg name; otherwise the raw 'Last, First' from mtgelo.
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

    Determines player_a/player_b by lexicographic comparison of mtgeloproject player_ids.
    Result, game_score, and Elo info reflect player_a's perspective; for fields the
    unfetched side leaves unfilled (elo_post / elo_delta), uses NaN.
    """
    by_match: dict[int, list[ProfileMatch]] = {}
    for r in rows:
        by_match.setdefault(r.match_id, []).append(r)

    merged: list[MergedMatch] = []
    nan = float("nan")
    for match_id, perspectives in by_match.items():
        # Each perspective contributes its own player_id + opponent_id.
        # The two player_ids identify both sides; pick the lower as player_a.
        ids = sorted({pid for r in perspectives for pid in (r.player_id, r.opponent_id)})
        if len(ids) != 2:
            continue  # corrupt; skip defensively
        a_id, b_id = ids[0], ids[1]

        # Find a ProfileMatch fetched from each side, if any
        from_a = next((r for r in perspectives if r.player_id == a_id), None)
        from_b = next((r for r in perspectives if r.player_id == b_id), None)
        if from_a is None and from_b is None:
            continue

        if from_a is not None:
            a_name = from_a.player_name
        else:
            # only have B's perspective; B saw A as the opponent
            a_name = from_b.opponent_name  # raw "Last, First"

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
            a_elo_pre = from_b.opp_elo_pre  # B's view of A's pre-Elo
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
    """'2-3' -> '3-2', etc. Empty string passes through."""
    if "-" not in score:
        return score
    a, _, b = score.partition("-")
    return f"{b}-{a}"
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: 18 passed (10 existing + 8 new).

If `find_player_id` fails on the fixtures, open the relevant `tests/fixtures/mtgelo/search-results-*.html` and inspect the actual `<astro-island>` props or disambig markup. The spike notes captured the field name as `playerid`. If a fixture uses a different shape, adjust the parser to match what the fixture actually contains (treat fixture as ground truth).

- [ ] **Step 5: Add orchestrator (`main()` + helpers)**

Append:

```python
def scrape_all_players(
    fetcher: _FetcherProtocol,
    roster: list[str],
) -> tuple[list[ProfileMatch], list[str]]:
    """Resolve each magic.gg name to an mtgelo player_id, fetch their matches JSON,
    and return (all_perspectives, unresolved_names)."""
    all_perspectives: list[ProfileMatch] = []
    unresolved: list[str] = []
    for name in roster:
        pid = find_player_id(fetcher, name)
        if not pid:
            unresolved.append(name)
            continue
        api_url = MATCHES_API_BASE.format(player_id=pid)
        body = fetcher.get(api_url)
        all_perspectives.extend(parse_matches_json(body, player_name=name, player_id=pid))
    return all_perspectives, unresolved


def write_matches_csv(matches: list[MergedMatch], out_path: Path) -> None:
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
    from mtg_scrape.fetch import Fetcher
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--decks", default="data/decks.csv")
    parser.add_argument("--out", default="data/matches.csv")
    args = parser.parse_args()

    fetcher = Fetcher(cache_dir=Path(args.cache_dir), min_interval_s=1.0)
    roster = _load_roster(Path(args.decks))
    perspectives, unresolved = scrape_all_players(fetcher, roster)
    merged = merge_match_perspectives(perspectives)
    write_matches_csv(merged, Path(args.out))

    print(f"Wrote {len(merged)} matches to {args.out}")
    if unresolved:
        print(f"WARNING: {len(unresolved)} players could not be resolved on mtgeloproject:")
        for n in unresolved:
            print(f"  - {n}")
        print("Note: their matches still appear from opponents' fetches as single-sided rows.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run end-to-end against live mtgeloproject**

Run: `.venv/bin/python -m mtg_scrape.matches_mtgelo`

Expected runtime: ~325 search GETs + ~325 API GETs × 1 req/sec ≈ 12 minutes on first run; subsequent runs use cache and finish in seconds. Console output should print roughly: "Wrote N matches to data/matches.csv" where N is in the low thousands (8 Standard rounds × ~325 players ÷ 2 ≈ 1300 Standard matches, plus similar for draft + top 8 = ~2200-2600 total).

Inspect `data/matches.csv` for sanity: row count, format column shows mostly "standard" and "draft", a finals row (round="F") with `match_id=4015653` and both players named/identified.

If `unresolved` is non-empty, that's expected for a few players (typos, accent edge cases). Note them; Task 9 will surface them again at join time and we'll add overrides as needed.

- [ ] **Step 7: Commit**

```
git add mtg_scrape/matches_mtgelo.py tests/test_matches_mtgelo.py data/matches.csv
git commit -m "Orchestrate mtgelo search + matches API + per-match dedupe"
```

- [ ] **Step 6: Run the scraper end-to-end**

Run: `.venv/bin/python -m mtg_scrape.matches_mtgelo`

Expected: prints `Wrote N matches to data/matches.csv` where N is in the low-to-mid thousands (325 players × ~16 swiss rounds ÷ 2 ≈ 2600 matches — high-end estimate; actual will be lower with drops and unresolved players).

If many players are unresolved, inspect a few — likely accent/name-shortening issues. Add rows to `data/name_overrides.csv` and re-run. Cache means re-runs are fast.

- [ ] **Step 7: Commit**

```
git add mtg_scrape/matches_mtgelo.py tests/test_matches_mtgelo.py data/matches.csv data/name_overrides.csv
git commit -m "Scrape and dedupe mtgeloproject matches end-to-end"
```

---

## Task 9: Join decks + matches into final matchups dataset

Filter to Standard rounds, join archetypes + Elo onto each match, derive `players.csv`, surface any unresolved names loudly.

**Files:**
- Create: `mtg_scrape/build_matchups.py`
- Create: `tests/test_build_matchups.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_build_matchups.py`:

```python
import pandas as pd
import pytest

from mtg_scrape.build_matchups import build_matchups, derive_players, UnresolvedNamesError


def _decks_df():
    return pd.DataFrame([
        {"player_name": "Nathan Steuer", "archetype_magicgg": "Selesnya Landfall",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Reid Duke", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])


def _matches_df():
    # round 1: Booster Draft (should be filtered out)
    # round 4: Standard
    return pd.DataFrame([
        {"round": 1, "format": "Booster Draft",
         "player_a": "Nathan Steuer", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-0",
         "player_a_elo_pre": 1900.0, "player_a_elo_delta": 5.0,
         "player_b_elo_pre": 1850.0, "player_b_elo_delta": -5.0},
        {"round": 4, "format": "Standard",
         "player_a": "Nathan Steuer", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-1",
         "player_a_elo_pre": 1905.0, "player_a_elo_delta": 7.0,
         "player_b_elo_pre": 1845.0, "player_b_elo_delta": -7.0},
    ])


def test_filters_to_standard_rounds():
    out = build_matchups(_decks_df(), _matches_df())
    assert list(out["round"]) == [4], "Booster Draft round should be excluded"


def test_joins_archetype_per_side():
    out = build_matchups(_decks_df(), _matches_df())
    row = out.iloc[0]
    assert row["archetype_a"] == "Selesnya Landfall"
    assert row["archetype_b"] == "Izzet Prowess"


def test_joins_elo_per_side():
    out = build_matchups(_decks_df(), _matches_df())
    row = out.iloc[0]
    assert row["elo_a_pre"] == 1905.0
    assert row["elo_b_pre"] == 1845.0


def test_raises_on_unresolved_name():
    matches = _matches_df().copy()
    matches.loc[1, "player_b"] = "Ghost Player"  # not in decks
    with pytest.raises(UnresolvedNamesError) as exc:
        build_matchups(_decks_df(), matches)
    assert "Ghost Player" in str(exc.value)


def test_normalization_resolves_accent_mismatches():
    # decks.csv has accents; matches.csv (from mtgelo) doesn't. No override needed,
    # because normalize() folds accents.
    decks = pd.DataFrame([
        {"player_name": "Javier Domínguez", "archetype_magicgg": "Esper Control",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Reid Duke", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])
    matches = pd.DataFrame([
        {"round": 4, "format": "Standard",
         "player_a": "Javier Dominguez", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-1",
         "player_a_elo_pre": 1800.0, "player_a_elo_delta": 5.0,
         "player_b_elo_pre": 1820.0, "player_b_elo_delta": -5.0},
    ])
    out = build_matchups(decks, matches)
    assert out.iloc[0]["player_a"] == "Javier Domínguez"  # canonical spelling restored


def test_overrides_resolve_substantial_name_mismatches():
    # magic.gg has "Sam Black"; mtgelo says "Samuel Black". User adds override.
    decks = pd.DataFrame([
        {"player_name": "Sam Black", "archetype_magicgg": "Mardu Sacrifice",
         "mainboard": "", "sideboard": ""},
        {"player_name": "Reid Duke", "archetype_magicgg": "Izzet Prowess",
         "mainboard": "", "sideboard": ""},
    ])
    matches = pd.DataFrame([
        {"round": 4, "format": "Standard",
         "player_a": "Samuel Black", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-1",
         "player_a_elo_pre": 1800.0, "player_a_elo_delta": 5.0,
         "player_b_elo_pre": 1820.0, "player_b_elo_delta": -5.0},
    ])
    overrides = {"samuel black": "sam black"}  # as load_overrides would return
    out = build_matchups(decks, matches, overrides=overrides)
    assert out.iloc[0]["player_a"] == "Sam Black"
    assert out.iloc[0]["archetype_a"] == "Mardu Sacrifice"


def test_derive_players_extracts_starting_elo():
    matches = pd.DataFrame([
        {"round": 1, "format": "Booster Draft",
         "player_a": "Nathan Steuer", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-0",
         "player_a_elo_pre": 1900.0, "player_a_elo_delta": 5.0,
         "player_b_elo_pre": 1850.0, "player_b_elo_delta": -5.0},
        {"round": 4, "format": "Standard",
         "player_a": "Nathan Steuer", "player_b": "Reid Duke", "result": "W",
         "game_score": "2-1",
         "player_a_elo_pre": 1905.0, "player_a_elo_delta": 7.0,
         "player_b_elo_pre": 1845.0, "player_b_elo_delta": -7.0},
    ])
    players = derive_players(matches)
    nathan = players.set_index("player_name").loc["Nathan Steuer"]
    assert nathan["starting_elo"] == 1900.0  # min round = round 1
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchups.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `mtg_scrape/build_matchups.py`**

```python
"""Join decks.csv and matches.csv into matchups.csv (constructed-only) and players.csv."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from mtg_scrape.names import build_resolver, load_overrides


class UnresolvedNamesError(RuntimeError):
    """Raised when matches reference players that cannot be resolved to a decklist owner."""


def build_matchups(
    decks: pd.DataFrame,
    matches: pd.DataFrame,
    overrides: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Filter matches to Standard rounds and join archetype + Elo per side.

    Names in matches (from mtgeloproject) are resolved to canonical decks-side names
    via accent/case folding (always) and the overrides map (if substantial differences
    exist). Raises UnresolvedNamesError if any resolution fails.
    """
    if overrides is None:
        overrides = {}

    canonical = decks["player_name"].tolist()
    resolver = build_resolver(canonical, overrides)

    working = matches.copy()
    working["player_a_resolved"] = working["player_a"].apply(resolver)
    working["player_b_resolved"] = working["player_b"].apply(resolver)

    unresolved = sorted(
        set(working.loc[working["player_a_resolved"].isna(), "player_a"].unique())
        | set(working.loc[working["player_b_resolved"].isna(), "player_b"].unique())
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

    standard = working[working["format"] == "Standard"].copy()

    decks_idx = decks.set_index("player_name")
    standard["archetype_a"] = standard["player_a"].map(decks_idx["archetype_magicgg"])
    standard["archetype_b"] = standard["player_b"].map(decks_idx["archetype_magicgg"])
    standard = standard.rename(columns={
        "player_a_elo_pre": "elo_a_pre",
        "player_b_elo_pre": "elo_b_pre",
    })

    return standard[[
        "round", "player_a", "archetype_a", "elo_a_pre",
        "player_b", "archetype_b", "elo_b_pre", "result",
    ]].reset_index(drop=True)


def derive_players(matches: pd.DataFrame) -> pd.DataFrame:
    """Extract per-player starting Elo: their pre-match Elo in the earliest round they played."""
    a = matches[["round", "player_a", "player_a_elo_pre"]].rename(
        columns={"player_a": "player_name", "player_a_elo_pre": "elo_pre"})
    b = matches[["round", "player_b", "player_b_elo_pre"]].rename(
        columns={"player_b": "player_name", "player_b_elo_pre": "elo_pre"})
    long = pd.concat([a, b], ignore_index=True).dropna(subset=["elo_pre"])
    if long.empty:
        return pd.DataFrame(columns=["player_name", "starting_elo"])
    idx = long.groupby("player_name")["round"].idxmin()
    starting = long.loc[idx, ["player_name", "elo_pre"]].rename(columns={"elo_pre": "starting_elo"})
    return starting.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decks", default="data/decks.csv")
    parser.add_argument("--matches", default="data/matches.csv")
    parser.add_argument("--overrides", default="data/name_overrides.csv")
    parser.add_argument("--matchups-out", default="data/matchups.csv")
    parser.add_argument("--players-out", default="data/players.csv")
    args = parser.parse_args()

    decks = pd.read_csv(args.decks)
    matches = pd.read_csv(args.matches)
    overrides = load_overrides(Path(args.overrides))

    matchups = build_matchups(decks, matches, overrides=overrides)
    matchups.to_csv(args.matchups_out, index=False)
    print(f"Wrote {len(matchups)} matchups to {args.matchups_out}")

    players = derive_players(matches)
    players.to_csv(args.players_out, index=False)
    print(f"Wrote {len(players)} players to {args.players_out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `.venv/bin/pytest tests/test_build_matchups.py -v`
Expected: 7 passed.

- [ ] **Step 5: Run end-to-end against real data**

Run: `.venv/bin/python -m mtg_scrape.build_matchups`
Expected: prints two `Wrote N ...` lines. If it raises `UnresolvedNamesError`, the error message lists which names need overrides — handle them and re-run.

Open `data/matchups.csv`: visually sanity check. Row count for a typical 8-Standard-round PT with 325 players is in the 1200-1300 range (8 × 325 ÷ 2, minus drops).

- [ ] **Step 6: Commit**

```
git add mtg_scrape/build_matchups.py tests/test_build_matchups.py data/matchups.csv data/players.csv
git commit -m "Join decks and matches into matchups + players datasets"
```

---

## Task 10: End-to-end smoke + final sanity check

Run the whole pipeline cold (clean cache) once to confirm it's reproducible, then sanity-check the output.

**Files:**
- Modify: `README.md` (add brief pipeline notes if anything changed)

- [ ] **Step 1: Run all tests**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Smoke-run from scratch**

Don't actually clear the cache (that would re-fetch ~700 pages over ~12 minutes). Just confirm the three scripts run cleanly with the cache populated:

```
.venv/bin/python -m mtg_scrape.decks_magicgg
.venv/bin/python -m mtg_scrape.matches_mtgelo
.venv/bin/python -m mtg_scrape.build_matchups
```

Expected: each prints its `Wrote N ...` line, no errors.

- [ ] **Step 3: Quick sanity check in a shell**

Run: `.venv/bin/python -c "import pandas as pd; m=pd.read_csv('data/matchups.csv'); print(m.shape); print(m['archetype_a'].value_counts().head()); print(m['archetype_b'].value_counts().head())"`

Expected:
- Row count in the 1000-1500 range.
- Archetype distributions match published metagame breakdown (Izzet Prowess ~30%, Mono-Green Landfall ~19% per magic.gg's recap).

If something looks off (way too few matches, missing archetypes, NaN-heavy columns), inspect.

- [ ] **Step 4: Final commit**

If any small README tweaks or cleanups are needed:

```
git add -A
git commit -m "Final pipeline sanity check"
```

---

## Out of scope (deferred)

- Downstream analysis (notebook). The matchups dataset is the input — the notebook lives outside this plan.
- Generalizing to other PTs. URLs and event names are hardcoded.
- Live updates. One-shot scrape.
- Draft (Limited) deck contents. Only Standard decks are captured.
