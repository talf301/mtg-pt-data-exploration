"""Parse magic.gg's PT Secrets of Strixhaven Standard decklist pages."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from mtg_scrape.fetch import Fetcher

# Confirmed during Task 3 snapshot run; all four surname buckets exist on magic.gg.
URLS = [
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-a-f",
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-g-l",
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-m-r",
    "https://magic.gg/decklists/pro-tour-secrets-of-strixhaven-standard-decklists-s-z",
]


@dataclass
class Deck:
    player_name: str
    archetype_magicgg: str
    mainboard: list[tuple[int, str]] = field(default_factory=list)
    sideboard: list[tuple[int, str]] = field(default_factory=list)


def parse_decklist_page(html: str) -> list[Deck]:
    """Parse one magic.gg decklist bucket page into Deck records.

    magic.gg uses custom HTML elements:
        <deck-list deck-title="Player Name" subtitle="Archetype" ...>
          <main-deck>
            7 Island
            3 Sunderflock
            ...
          </main-deck>
          <side-board>
            ...
          </side-board>
        </deck-list>
    """
    soup = BeautifulSoup(html, "lxml")
    decks: list[Deck] = []

    for block in soup.find_all("deck-list"):
        player_name = (block.get("deck-title") or "").strip()
        archetype = (block.get("subtitle") or "").strip()
        if not player_name:
            continue

        deck = Deck(player_name=player_name, archetype_magicgg=archetype)

        main_el = block.find("main-deck")
        side_el = block.find("side-board")

        if main_el:
            deck.mainboard = _parse_card_block(main_el.get_text())
        if side_el:
            deck.sideboard = _parse_card_block(side_el.get_text())

        decks.append(deck)

    return decks


def _parse_card_block(text: str) -> list[tuple[int, str]]:
    """Parse newline-separated '<qty> <card name>' lines into [(qty, name), ...].

    Skips blank lines. Tolerates leading/trailing whitespace on each line.
    """
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        qty_str, _, name = line.partition(" ")
        try:
            qty = int(qty_str)
        except ValueError:
            continue
        name = name.strip()
        if not name:
            continue
        out.append((qty, name))
    return out


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
            w.writerow([
                d.player_name,
                d.archetype_magicgg,
                _serialize_cards(d.mainboard),
                _serialize_cards(d.sideboard),
            ])


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
