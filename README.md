# mtg-pt-data-exploration

Scrape and analyze match and deck data from Pro Tour Secrets of Strixhaven.

## Setup

```sh
uv venv
uv pip install -e ".[dev]"
```

## Pipeline

The scrape + build pipeline runs in three steps:

1. `python -m mtg_scrape.decks_magicgg` — scrape deck data from magic.gg.
2. `python -m mtg_scrape.matches_mtgelo` — scrape match data from mtgelo.
3. `python -m mtg_scrape.build_matchups` — join decks and matches into a matchups table.

## Design

See [docs/superpowers/specs/2026-05-21-pt-strixhaven-scraper-design.md](docs/superpowers/specs/2026-05-21-pt-strixhaven-scraper-design.md) for the design spec.
