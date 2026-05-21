"""Normalize player names and resolve cross-source mismatches.

magic.gg lists "First Last"; mtgeloproject's JSON returns "Last, First".
`normalize` folds both to the same canonical form. `build_resolver`
returns a lookup function from any spelling to the canonical magic.gg name.
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Callable, Iterable


def normalize(name: str | None) -> str:
    """Fold case, swap "Last, First" -> "First Last", strip accents, collapse whitespace."""
    if not name:
        return ""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            name = f"{parts[1]} {parts[0]}"
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(no_accents.lower().split())


def load_overrides(path: Path) -> dict[str, str]:
    """Load overrides CSV. Returns mapping normalized-mtgelo -> normalized-magic.gg.

    CSV format: magic_gg_name, mtgelo_name
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
      1. Accent/case/comma/whitespace-folded direct match against canonical_names.
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
