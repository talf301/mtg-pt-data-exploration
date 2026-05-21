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
