"""Spike: fetch representative mtgeloproject pages and freeze them.

We need to confirm:
 - URL pattern for searching by player name
 - URL pattern for a player profile
 - Per-match data shape (round, format, opponent, result, Elo, delta)
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
        "faq.html": "https://mtgeloproject.net/faq",
        "leaders-all.html": "https://mtgeloproject.net/leaders/all",
        # Christoffer Larsen — linked from the home page
        "sample-player-larsen.html": "https://mtgeloproject.net/profile/wrr61zbv",
        # Profile React component bundle — to find the API endpoint it calls
        "profile-bundle.js": "https://mtgeloproject.net/_astro/Profile.AWCtGaC_.js",
        # Search React component bundle — to find the search/autocomplete endpoint
        "search-bundle.js": "https://mtgeloproject.net/_astro/Search.Cy44HT0L.js",
        # MobileMenu bundle (contains the actual SearchBoxes component used by Search)
        "mobilemenu-bundle.js": "https://mtgeloproject.net/_astro/MobileMenu.D_j8CVtT.js",
        # Search results page — try Nathan Steuer (PT SOS winner)
        "search-results-steuer.html": "https://mtgeloproject.net/search/Steuer/Nathan",
        # JSON API: events list for Larsen
        "api-events-larsen.json": "https://mtgeloproject.net/api/players/wrr61zbv/events",
        # JSON API: matches for Larsen
        "api-matches-larsen.json": "https://mtgeloproject.net/api/players/wrr61zbv/matches",
        # Sanity check: Nathan Steuer (PT SOS winner) matches via JSON API
        "api-matches-steuer.json": "https://mtgeloproject.net/api/players/zz14clya/matches",
        # Search with multiple results — common surname, no first name
        "search-results-smith.html": "https://mtgeloproject.net/search/Smith/*",
        # Multi-result, moderately uncommon surname — should list candidates
        "search-results-larsen.html": "https://mtgeloproject.net/search/Larsen/*",
        # Invalid search — sanity check error shape
        "search-results-noone.html": "https://mtgeloproject.net/search/Zzzzqqqxx/*",
    }
    for fname, url in targets.items():
        try:
            html = fetcher.get(url)
            (fixtures / fname).write_text(html, encoding="utf-8")
            print(f"OK   {fname} <- {url}")
        except Exception as exc:
            print(f"FAIL {fname} <- {url}: {exc}")
