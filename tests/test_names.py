from pathlib import Path
import csv
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
    resolver = build_resolver(
        canonical_names=["Nathan Steuer", "Javier Domínguez"],
        overrides={},
    )
    assert resolver("nathan steuer") == "Nathan Steuer"
    assert resolver("Javier Dominguez") == "Javier Domínguez"  # accent-insensitive


def test_resolver_uses_override_for_substantial_name_differences():
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
    assert load_overrides(p) == {"samuel black": "sam black"}
