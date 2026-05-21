from pathlib import Path
import pytest
from mtg_scrape.decks_magicgg import parse_decklist_page

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "magicgg"

EXPECTED_COUNTS = {
    "a-f": 82,
    "g-l": 83,
    "m-r": 78,
    "s-z": 82,
}
TOTAL_EXPECTED = 325


def _load(suffix: str) -> str:
    return (FIXTURE_DIR / f"decklists-{suffix}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", list(EXPECTED_COUNTS))
def test_parses_expected_deck_count_per_bucket(suffix):
    decks = parse_decklist_page(_load(suffix))
    assert len(decks) == EXPECTED_COUNTS[suffix], (
        f"bucket {suffix}: expected {EXPECTED_COUNTS[suffix]} decks, got {len(decks)}"
    )


def test_all_fixtures_sum_to_full_field():
    total = sum(len(parse_decklist_page(_load(s))) for s in EXPECTED_COUNTS)
    assert total == TOTAL_EXPECTED


@pytest.mark.parametrize("suffix", list(EXPECTED_COUNTS))
def test_every_deck_has_player_and_archetype_and_mainboard(suffix):
    decks = parse_decklist_page(_load(suffix))
    for d in decks:
        assert d.player_name, f"empty player_name in bucket {suffix}"
        assert d.archetype_magicgg, f"empty archetype for {d.player_name} in bucket {suffix}"
        assert d.mainboard, f"empty mainboard for {d.player_name} in bucket {suffix}"


@pytest.mark.parametrize("suffix", list(EXPECTED_COUNTS))
def test_mainboard_cards_have_qty_and_name(suffix):
    decks = parse_decklist_page(_load(suffix))
    for d in decks:
        for qty, name in d.mainboard:
            assert isinstance(qty, int) and qty > 0, f"bad qty for {d.player_name}"
            assert isinstance(name, str) and name, f"bad card name for {d.player_name}"


@pytest.mark.parametrize("suffix", list(EXPECTED_COUNTS))
def test_mainboard_total_is_at_least_60_for_standard(suffix):
    decks = parse_decklist_page(_load(suffix))
    for d in decks:
        total = sum(qty for qty, _ in d.mainboard)
        assert total >= 60, f"{d.player_name} ({suffix}) mainboard total {total} < 60"


@pytest.mark.parametrize("suffix", list(EXPECTED_COUNTS))
def test_sideboard_total_is_at_most_15(suffix):
    decks = parse_decklist_page(_load(suffix))
    for d in decks:
        total = sum(qty for qty, _ in d.sideboard)
        assert total <= 15, f"{d.player_name} ({suffix}) sideboard total {total} > 15"


def test_spot_check_known_deck():
    """Junichi Adachi appears in a-f with Izzet Spellementals; mainboard starts with 7 Island."""
    decks = parse_decklist_page(_load("a-f"))
    by_name = {d.player_name: d for d in decks}
    assert "Junichi Adachi" in by_name, "Junichi Adachi missing from a-f bucket"
    d = by_name["Junichi Adachi"]
    assert d.archetype_magicgg == "Izzet Spellementals"
    assert d.mainboard[0] == (7, "Island")
