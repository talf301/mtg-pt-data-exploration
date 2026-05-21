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
