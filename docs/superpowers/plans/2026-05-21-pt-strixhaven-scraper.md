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
Expected: 8 passed.

- [ ] **Step 6: Commit**

```
git add mtg_scrape/names.py tests/test_names.py data/name_overrides.csv
git commit -m "Add name normalization and override resolver"
```

---

## Task 7: mtgeloproject profile parser (TDD against fixture)

Parse one mtgeloproject player-profile HTML page into a list of `MatchRow` records covering that player's matches at PT Strixhaven. Selectors derived from the fixtures saved in Task 5.

**Files:**
- Create: `mtg_scrape/matches_mtgelo.py` (parser only, in this task; orchestrator in Task 8)
- Create: `tests/test_matches_mtgelo.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_matches_mtgelo.py`:

```python
from pathlib import Path
from mtg_scrape.matches_mtgelo import parse_profile_matches, ProfileMatch

FIXTURE = Path(__file__).parent / "fixtures" / "mtgelo" / "sample-player.html"


def test_returns_some_matches_for_pt_strixhaven():
    html = FIXTURE.read_text(encoding="utf-8")
    matches = parse_profile_matches(html, event_filter="Pro Tour Secrets of Strixhaven")
    assert len(matches) >= 8, f"expected at least 8 rounds, got {len(matches)}"


def test_match_has_required_fields():
    html = FIXTURE.read_text(encoding="utf-8")
    matches = parse_profile_matches(html, event_filter="Pro Tour Secrets of Strixhaven")
    m = matches[0]
    assert isinstance(m, ProfileMatch)
    assert isinstance(m.round_number, int) and m.round_number >= 1
    assert m.format_tag in {"Standard", "Booster Draft", "Limited", "Constructed"}
    assert m.opponent_name and isinstance(m.opponent_name, str)
    assert m.result in {"W", "L", "D"}
    assert m.elo_pre is None or isinstance(m.elo_pre, float)
    assert m.elo_delta is None or isinstance(m.elo_delta, float)


def test_filters_to_event():
    html = FIXTURE.read_text(encoding="utf-8")
    all_matches = parse_profile_matches(html, event_filter=None)
    pt_matches = parse_profile_matches(html, event_filter="Pro Tour Secrets of Strixhaven")
    assert len(all_matches) >= len(pt_matches)
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement parser portion of `mtg_scrape/matches_mtgelo.py`**

Selectors must match what Task 5 found. Skeleton:

```python
"""Scrape mtgeloproject.net player profiles for PT Secrets of Strixhaven matches.

The scraper:
  1. Reads the player roster from data/decks.csv.
  2. For each player, looks up their mtgeloproject profile URL via the
     site's search.
  3. Fetches the profile and extracts their PT Strixhaven matches with Elo Δ.
  4. Dedupes across players by (round_number, frozenset(player_pair)),
     merging Elo info from both perspectives.
  5. Writes data/matches.csv.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from mtg_scrape.fetch import Fetcher
from mtg_scrape.names import normalize


EVENT_NAME = "Pro Tour Secrets of Strixhaven"


@dataclass
class ProfileMatch:
    """One match as seen from one player's profile."""
    player_name: str        # whose profile this came from
    round_number: int
    format_tag: str         # "Standard", "Booster Draft", etc.
    opponent_name: str
    result: str             # "W" / "L" / "D" from player_name's perspective
    game_score: str | None  # "2-1" or None if not exposed
    elo_pre: float | None
    elo_delta: float | None
    event_name: str         # so we can filter


def parse_profile_matches(html: str, event_filter: str | None = EVENT_NAME) -> list[ProfileMatch]:
    """Parse a player profile page into ProfileMatch rows.

    `event_filter`: if not None, only return matches whose event_name contains this string.
    """
    soup = BeautifulSoup(html, "lxml")

    # ----- REPLACE WITH REAL SELECTORS FROM TASK 5 FIXTURES -----
    # Pseudocode for shape; actual selectors depend on the live page.
    player_name = (soup.select_one("h1, .player-name") or soup.title).get_text(strip=True)
    rows: list[ProfileMatch] = []
    for tr in soup.select("table.matches tr.match-row"):
        event_el = tr.select_one(".event")
        event_name = event_el.get_text(strip=True) if event_el else ""
        if event_filter and event_filter not in event_name:
            continue

        round_el = tr.select_one(".round")
        format_el = tr.select_one(".format")
        opp_el = tr.select_one(".opponent")
        res_el = tr.select_one(".result")
        score_el = tr.select_one(".game-score")
        elo_pre_el = tr.select_one(".elo-pre")
        elo_delta_el = tr.select_one(".elo-delta")

        if not (round_el and opp_el and res_el):
            continue

        rows.append(ProfileMatch(
            player_name=player_name,
            round_number=int(round_el.get_text(strip=True)),
            format_tag=(format_el.get_text(strip=True) if format_el else ""),
            opponent_name=opp_el.get_text(strip=True),
            result=_normalize_result(res_el.get_text(strip=True)),
            game_score=(score_el.get_text(strip=True) if score_el else None),
            elo_pre=_parse_float(elo_pre_el),
            elo_delta=_parse_float(elo_delta_el),
            event_name=event_name,
        ))
    return rows


def _normalize_result(text: str) -> str:
    t = text.strip().upper()
    if t.startswith("W"):
        return "W"
    if t.startswith("L"):
        return "L"
    return "D"


def _parse_float(el) -> float | None:
    if el is None:
        return None
    txt = el.get_text(strip=True).replace("+", "")
    try:
        return float(txt)
    except ValueError:
        return None
```

- [ ] **Step 4: Iterate on selectors until tests pass**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Open `tests/fixtures/mtgelo/sample-player.html` and adjust selectors to match the real DOM. Re-run until 3 tests pass.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/matches_mtgelo.py tests/test_matches_mtgelo.py
git commit -m "Parse mtgeloproject profile matches"
```

---

## Task 8: mtgeloproject orchestrator — search, walk, dedupe

Add the orchestration layer to `matches_mtgelo.py`: name → profile URL search, walk all 325 profiles, dedupe matches across both players' views, write `data/matches.csv`.

**Files:**
- Modify: `mtg_scrape/matches_mtgelo.py`
- Modify: `tests/test_matches_mtgelo.py`

- [ ] **Step 1: Write failing tests for the dedupe logic**

Append to `tests/test_matches_mtgelo.py`:

```python
from mtg_scrape.matches_mtgelo import merge_match_perspectives, MergedMatch, ProfileMatch


def _pm(player, opp, result, elo_pre, elo_delta, round_=4, fmt="Standard"):
    return ProfileMatch(
        player_name=player, round_number=round_, format_tag=fmt,
        opponent_name=opp, result=result, game_score="2-1",
        elo_pre=elo_pre, elo_delta=elo_delta, event_name="Pro Tour Secrets of Strixhaven",
    )


def test_merge_two_perspectives_into_one_row():
    a = _pm("Nathan Steuer", "Reid Duke", "W", 1850.0, +12.0)
    b = _pm("Reid Duke", "Nathan Steuer", "L", 1830.0, -12.0)

    merged = merge_match_perspectives([a, b])

    assert len(merged) == 1
    m = merged[0]
    assert {m.player_a, m.player_b} == {"Nathan Steuer", "Reid Duke"}
    if m.player_a == "Nathan Steuer":
        assert m.result == "W"
        assert m.player_a_elo_pre == 1850.0
        assert m.player_b_elo_pre == 1830.0
    else:
        assert m.result == "L"


def test_merge_single_sided_keeps_other_side_null():
    only = _pm("Nathan Steuer", "Unknown Player", "W", 1850.0, +12.0)
    merged = merge_match_perspectives([only])
    assert len(merged) == 1
    m = merged[0]
    assert m.player_a_elo_pre == 1850.0
    assert m.player_b_elo_pre is None


def test_merge_orders_players_alphabetically():
    a = _pm("Nathan Steuer", "Reid Duke", "W", 1850.0, +12.0)
    b = _pm("Reid Duke", "Nathan Steuer", "L", 1830.0, -12.0)
    merged = merge_match_perspectives([a, b])
    assert merged[0].player_a == "Nathan Steuer"  # alphabetically first
    assert merged[0].player_b == "Reid Duke"
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: 3 new failures (existing 3 still pass).

- [ ] **Step 3: Add `MergedMatch` and `merge_match_perspectives` to `matches_mtgelo.py`**

Append to `mtg_scrape/matches_mtgelo.py`:

```python
@dataclass
class MergedMatch:
    round_number: int
    format_tag: str
    player_a: str               # alphabetically first
    player_b: str
    result: str                 # from player_a's perspective: "W"/"L"/"D"
    game_score: str | None
    player_a_elo_pre: float | None
    player_a_elo_delta: float | None
    player_b_elo_pre: float | None
    player_b_elo_delta: float | None


def merge_match_perspectives(rows: Iterable[ProfileMatch]) -> list[MergedMatch]:
    """Dedupe matches that appear once per player perspective into single rows.

    Key: (round_number, frozenset({player_name, opponent_name})). For each key,
    we may see 0, 1, or 2 perspectives. Each perspective contributes one side's
    Elo info; the result column flips with which side is player_a.
    """
    # Group by key
    by_key: dict[tuple[int, frozenset[str]], list[ProfileMatch]] = {}
    for r in rows:
        key = (r.round_number, frozenset({r.player_name, r.opponent_name}))
        by_key.setdefault(key, []).append(r)

    merged: list[MergedMatch] = []
    for key, perspectives in by_key.items():
        names = sorted({n for r in perspectives for n in (r.player_name, r.opponent_name)})
        if len(names) == 1:
            # Self-match? Shouldn't happen; skip defensively.
            continue
        player_a, player_b = names[0], names[1]

        from_a = next((r for r in perspectives if r.player_name == player_a), None)
        from_b = next((r for r in perspectives if r.player_name == player_b), None)
        sample = from_a or from_b
        assert sample is not None

        # Determine result from player_a's perspective:
        if from_a is not None:
            result_a = from_a.result
        else:
            # Only have from_b; flip B's result
            assert from_b is not None
            result_a = {"W": "L", "L": "W", "D": "D"}[from_b.result]

        merged.append(MergedMatch(
            round_number=sample.round_number,
            format_tag=sample.format_tag,
            player_a=player_a,
            player_b=player_b,
            result=result_a,
            game_score=sample.game_score,
            player_a_elo_pre=from_a.elo_pre if from_a else None,
            player_a_elo_delta=from_a.elo_delta if from_a else None,
            player_b_elo_pre=from_b.elo_pre if from_b else None,
            player_b_elo_delta=from_b.elo_delta if from_b else None,
        ))
    merged.sort(key=lambda m: (m.round_number, m.player_a))
    return merged
```

- [ ] **Step 4: Run dedupe tests, confirm pass**

Run: `.venv/bin/pytest tests/test_matches_mtgelo.py -v`
Expected: 6 passed.

- [ ] **Step 5: Add search-by-name resolver and end-to-end scrape**

Append to `mtg_scrape/matches_mtgelo.py`:

```python
# URL patterns confirmed during Task 5 spike. Update these if mtgeloproject changes its URLs.
SEARCH_URL = "https://mtgeloproject.net/search?name={query}"
PROFILE_LINK_SELECTOR = "a.player-link"  # update per spike findings


def find_profile_url(fetcher: Fetcher, player_name: str) -> str | None:
    """Use mtgeloproject's name search to find a player's profile URL.

    Returns absolute URL or None if no match.
    """
    html = fetcher.get(SEARCH_URL.format(query=quote_plus(player_name)))
    soup = BeautifulSoup(html, "lxml")
    target_norm = normalize(player_name)
    for link in soup.select(PROFILE_LINK_SELECTOR):
        label = link.get_text(strip=True)
        if normalize(label) == target_norm:
            href = link.get("href", "")
            if href.startswith("http"):
                return href
            return f"https://mtgeloproject.net{href}"
    # Fallback: take the first result if its normalized name matches.
    first = soup.select_one(PROFILE_LINK_SELECTOR)
    if first and normalize(first.get_text(strip=True)) == target_norm:
        href = first.get("href", "")
        return href if href.startswith("http") else f"https://mtgeloproject.net{href}"
    return None


def scrape_all_profiles(fetcher: Fetcher, players: list[str]) -> tuple[list[ProfileMatch], list[str]]:
    """Walk every player's profile, return (all_perspectives, unresolved_names)."""
    all_perspectives: list[ProfileMatch] = []
    unresolved: list[str] = []
    for name in players:
        url = find_profile_url(fetcher, name)
        if not url:
            unresolved.append(name)
            continue
        html = fetcher.get(url)
        all_perspectives.extend(parse_profile_matches(html, event_filter=EVENT_NAME))
    return all_perspectives, unresolved


def write_matches_csv(matches: list[MergedMatch], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "round", "format", "player_a", "player_b", "result", "game_score",
            "player_a_elo_pre", "player_a_elo_delta",
            "player_b_elo_pre", "player_b_elo_delta",
        ])
        for m in matches:
            w.writerow([
                m.round_number, m.format_tag, m.player_a, m.player_b, m.result,
                m.game_score or "",
                m.player_a_elo_pre if m.player_a_elo_pre is not None else "",
                m.player_a_elo_delta if m.player_a_elo_delta is not None else "",
                m.player_b_elo_pre if m.player_b_elo_pre is not None else "",
                m.player_b_elo_delta if m.player_b_elo_delta is not None else "",
            ])


def _load_roster(decks_path: Path) -> list[str]:
    with decks_path.open("r", encoding="utf-8", newline="") as f:
        return [row["player_name"] for row in csv.DictReader(f)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--decks", default="data/decks.csv")
    parser.add_argument("--out", default="data/matches.csv")
    args = parser.parse_args()

    fetcher = Fetcher(cache_dir=Path(args.cache_dir), min_interval_s=1.0)
    roster = _load_roster(Path(args.decks))
    perspectives, unresolved = scrape_all_profiles(fetcher, roster)
    merged = merge_match_perspectives(perspectives)
    write_matches_csv(merged, Path(args.out))

    print(f"Wrote {len(merged)} matches to {args.out}")
    if unresolved:
        print(f"WARNING: {len(unresolved)} players could not be resolved on mtgeloproject:")
        for n in unresolved:
            print(f"  - {n}")
        print("Add overrides to data/name_overrides.csv and re-run.")


if __name__ == "__main__":
    main()
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
