# Archetype Matchup Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Python script that reads `data/matchups.csv` and emits four artifacts under `data/`: a string matchup matrix CSV, a numeric matchup matrix CSV, a counts matchup matrix CSV, and a heatmap PNG.

**Architecture:** One module (`mtg_scrape/build_matchup_matrix.py`) with small, testable functions: load → top-N selection + Other bucketing → long-frame expansion → matrix computation → render. Fixture-driven unit tests use synthetic DataFrames; smoke test verifies the four output files exist with the right shape.

**Tech Stack:** Python 3.11+, pandas (already a dep), matplotlib (new dep), pytest.

**Source of truth:** `docs/superpowers/specs/2026-05-21-matchup-matrix-design.md`

---

## Task 1: Add matplotlib dependency

The script needs `matplotlib` to render the heatmap PNG. Add it to `pyproject.toml` and reinstall.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add matplotlib to the dependency list**

Open `pyproject.toml`. Find the `dependencies = [...]` block. Add `"matplotlib>=3.8",` to it.

After edit, the block should look like:

```toml
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "pandas>=2.2",
    "matplotlib>=3.8",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `cd /home/tal/Documents/mtg-pt-data-exploration && uv pip install -e ".[dev]"`
Expected: matplotlib resolves and installs.

- [ ] **Step 3: Verify the import works**

Run: `.venv/bin/python -c "import matplotlib; print(matplotlib.__version__)"`
Expected: prints a version like `3.x.y`.

- [ ] **Step 4: Commit**

```
git add pyproject.toml
git commit -m "Add matplotlib dependency for matchup matrix heatmap"
```

---

## Task 2: Top-N archetype selection with "Other" mapping

A small pure function: given the matchups DataFrame and N, return a list of the top-N archetypes ordered by total appearances across both `archetype_a` and `archetype_b`, plus a mapping from every source archetype to either itself (if in top N) or `"Other"`.

**Files:**
- Create: `mtg_scrape/build_matchup_matrix.py`
- Create: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_build_matchup_matrix.py`:

```python
import pandas as pd
import pytest

from mtg_scrape.build_matchup_matrix import top_n_archetypes, map_to_bucket


def _matchups(rows):
    """Build a minimal matchups DataFrame from a list of (arch_a, arch_b, result)."""
    return pd.DataFrame(rows, columns=["archetype_a", "archetype_b", "result"])


def test_top_n_archetypes_ranks_by_total_appearances():
    # IzzetProwess appears 3 times, Mono-Green 2, Rogue 1. Top 2 should be Izzet, Mono-Green.
    m = _matchups([
        ("IzzetProwess",  "Mono-Green", "W"),
        ("IzzetProwess",  "Rogue",      "W"),
        ("Mono-Green",    "IzzetProwess", "L"),
    ])
    assert top_n_archetypes(m, n=2) == ["IzzetProwess", "Mono-Green"]


def test_top_n_archetypes_ties_broken_alphabetically():
    # Both archetypes have 1 appearance; tied -> alphabetical.
    m = _matchups([("Banana", "Apple", "W")])
    assert top_n_archetypes(m, n=2) == ["Apple", "Banana"]


def test_map_to_bucket_returns_other_for_non_top_n():
    bucket = map_to_bucket(["IzzetProwess", "Mono-Green"], other_label="Other")
    assert bucket("IzzetProwess") == "IzzetProwess"
    assert bucket("Mono-Green") == "Mono-Green"
    assert bucket("RogueDeck") == "Other"
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the two functions**

Create `mtg_scrape/build_matchup_matrix.py`:

```python
"""Compute the PT Strixhaven archetype matchup matrix and render CSVs + PNG."""
from __future__ import annotations

import pandas as pd

OTHER_LABEL = "Other"


def top_n_archetypes(matchups: pd.DataFrame, n: int = 10) -> list[str]:
    """Return the n most-played archetypes, by total appearances across both sides.

    Ties broken alphabetically.
    """
    counts = pd.concat([matchups["archetype_a"], matchups["archetype_b"]]).value_counts()
    # Convert to a DataFrame so we can sort by count desc, then name asc
    ordered = (
        counts.rename_axis("archetype")
        .reset_index(name="count")
        .sort_values(by=["count", "archetype"], ascending=[False, True])
    )
    return ordered.head(n)["archetype"].tolist()


def map_to_bucket(top_n: list[str], other_label: str = OTHER_LABEL):
    """Return a callable: archetype -> archetype if in top_n else other_label."""
    top_set = set(top_n)

    def _bucket(archetype: str) -> str:
        return archetype if archetype in top_set else other_label

    return _bucket
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py
git commit -m "Add top-N archetype selection + Other bucketing"
```

---

## Task 3: Long-frame expansion

Convert each matchup row into two long-frame rows (one per player's perspective). Drop draws. Apply the top-N bucketing.

**Files:**
- Modify: `mtg_scrape/build_matchup_matrix.py`
- Modify: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_matchup_matrix.py`:

```python
from mtg_scrape.build_matchup_matrix import to_long_frame


def test_to_long_frame_doubles_row_count():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("Mono-Green", "IzzetProwess", "L"),
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    assert len(long) == 4  # 2 input rows × 2 perspectives


def test_to_long_frame_flips_result_on_mirror_row():
    m = _matchups([("IzzetProwess", "Mono-Green", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    # Forward perspective: my_arch=IzzetProwess, result=W
    forward = long[long["my_arch"] == "IzzetProwess"].iloc[0]
    assert forward["opp_arch"] == "Mono-Green"
    assert forward["result"] == "W"
    # Mirror perspective: my_arch=Mono-Green, result flipped to L
    mirror = long[long["my_arch"] == "Mono-Green"].iloc[0]
    assert mirror["opp_arch"] == "IzzetProwess"
    assert mirror["result"] == "L"


def test_to_long_frame_drops_draws():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "D"),  # this one drops both perspectives
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    assert len(long) == 2  # only the W row's two perspectives survive
    assert "D" not in long["result"].values


def test_to_long_frame_buckets_non_top_n_to_other():
    m = _matchups([("IzzetProwess", "RogueDeck", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess"])
    rogue_rows = long[long["my_arch"] == "Other"]
    assert len(rogue_rows) == 1
    assert rogue_rows.iloc[0]["opp_arch"] == "IzzetProwess"
    assert rogue_rows.iloc[0]["result"] == "L"  # flipped from input W
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 4 new failures (`top_n_archetypes` / `map_to_bucket` still pass).

- [ ] **Step 3: Implement `to_long_frame`**

Append to `mtg_scrape/build_matchup_matrix.py`:

```python
_FLIP = {"W": "L", "L": "W"}


def to_long_frame(
    matchups: pd.DataFrame,
    top_n: list[str],
    other_label: str = OTHER_LABEL,
) -> pd.DataFrame:
    """Expand each matchups row into two long-frame rows (one per perspective).

    - Drops draws (result == "D").
    - Maps non-top-N archetypes to other_label.
    - Output columns: my_arch, opp_arch, result.
    """
    bucket = map_to_bucket(top_n, other_label=other_label)
    decided = matchups[matchups["result"].isin(_FLIP)].copy()

    forward = pd.DataFrame({
        "my_arch": decided["archetype_a"].map(bucket),
        "opp_arch": decided["archetype_b"].map(bucket),
        "result": decided["result"],
    })
    mirror = pd.DataFrame({
        "my_arch": decided["archetype_b"].map(bucket),
        "opp_arch": decided["archetype_a"].map(bucket),
        "result": decided["result"].map(_FLIP),
    })
    return pd.concat([forward, mirror], ignore_index=True)
```

- [ ] **Step 4: Run, confirm all pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py
git commit -m "Expand matchups into long-frame with mirror perspective"
```

---

## Task 4: Matrix computation (wins/losses + win rate)

Given the long-frame and a list of ordered labels, produce two square DataFrames: wins and losses, both indexed by `(my_arch, opp_arch)`. The diagonal is suppressed (NaN/0) since mirror matches always produce equal wins and losses.

**Files:**
- Modify: `mtg_scrape/build_matchup_matrix.py`
- Modify: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_matchup_matrix.py`:

```python
import math
from mtg_scrape.build_matchup_matrix import compute_matrix, compute_win_rate


def test_compute_matrix_counts_wins_and_losses_per_cell():
    # 3 matches: Izzet beats Mono-Green twice, Mono-Green beats Izzet once.
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "L"),
    ])
    long = to_long_frame(m, top_n=["IzzetProwess", "Mono-Green"])
    wins, losses = compute_matrix(long, ordered_labels=["IzzetProwess", "Mono-Green"])

    assert wins.loc["IzzetProwess", "Mono-Green"] == 2
    assert losses.loc["IzzetProwess", "Mono-Green"] == 1
    # Mirror cell: symmetric
    assert wins.loc["Mono-Green", "IzzetProwess"] == 1
    assert losses.loc["Mono-Green", "IzzetProwess"] == 2


def test_compute_matrix_diagonal_is_zero():
    """Mirror matches contribute equally to wins and losses on the diagonal."""
    m = _matchups([("IzzetProwess", "IzzetProwess", "W")])
    long = to_long_frame(m, top_n=["IzzetProwess"])
    wins, losses = compute_matrix(long, ordered_labels=["IzzetProwess"])
    # The W from player_a + the L from player_b contribute 1 win and 1 loss to diag.
    assert wins.loc["IzzetProwess", "IzzetProwess"] == 1
    assert losses.loc["IzzetProwess", "IzzetProwess"] == 1


def test_compute_win_rate_off_diagonal_is_wins_over_total():
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert wr.loc["A", "B"] == pytest.approx(2 / 3)
    assert wr.loc["B", "A"] == pytest.approx(1 / 3)


def test_compute_win_rate_diagonal_is_nan():
    wins = pd.DataFrame([[5, 2], [1, 5]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[5, 1], [2, 5]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert math.isnan(wr.loc["A", "A"])
    assert math.isnan(wr.loc["B", "B"])


def test_off_diagonal_symmetry_invariant():
    """For all off-diagonal (A, B): win_rate(A, B) + win_rate(B, A) == 1.0."""
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W"),
        ("IzzetProwess", "Mono-Green", "L"),
        ("IzzetProwess", "Mono-Green", "W"),
    ])
    labels = ["IzzetProwess", "Mono-Green"]
    long = to_long_frame(m, top_n=labels)
    wins, losses = compute_matrix(long, ordered_labels=labels)
    wr = compute_win_rate(wins, losses)
    assert wr.loc["IzzetProwess", "Mono-Green"] + wr.loc["Mono-Green", "IzzetProwess"] == pytest.approx(1.0)


def test_compute_win_rate_low_sample_cell_is_nan_when_zero_games():
    """A cell with no matches at all (no wins, no losses) should be NaN, not 0/0 = ZeroDivisionError."""
    wins = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    wr = compute_win_rate(wins, losses)
    assert math.isnan(wr.loc["A", "B"])
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 6 new failures.

- [ ] **Step 3: Implement `compute_matrix` and `compute_win_rate`**

Append to `mtg_scrape/build_matchup_matrix.py`:

```python
def compute_matrix(
    long: pd.DataFrame,
    ordered_labels: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute square wins and losses DataFrames indexed by (my_arch, opp_arch).

    Returns two DataFrames with rows=cols=ordered_labels (filling 0 where no data exists).
    """
    decided = long[long["result"].isin(("W", "L"))]
    wins_pivot = (
        decided[decided["result"] == "W"]
        .groupby(["my_arch", "opp_arch"]).size()
        .unstack(fill_value=0)
    )
    losses_pivot = (
        decided[decided["result"] == "L"]
        .groupby(["my_arch", "opp_arch"]).size()
        .unstack(fill_value=0)
    )
    wins = wins_pivot.reindex(index=ordered_labels, columns=ordered_labels, fill_value=0)
    losses = losses_pivot.reindex(index=ordered_labels, columns=ordered_labels, fill_value=0)
    return wins.astype(int), losses.astype(int)


def compute_win_rate(wins: pd.DataFrame, losses: pd.DataFrame) -> pd.DataFrame:
    """Compute the win rate matrix; suppress the diagonal to NaN."""
    total = wins + losses
    # Avoid 0/0 -> NaN via masking
    wr = wins.where(total > 0).astype(float).div(total.where(total > 0))
    # Suppress diagonal
    for label in wr.index:
        if label in wr.columns:
            wr.loc[label, label] = float("nan")
    return wr
```

- [ ] **Step 4: Run, confirm all pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py
git commit -m "Compute wins/losses matrix and win-rate; suppress diagonal"
```

---

## Task 5: CSV renderers

Three CSV outputs: a human-readable strings matrix ("53% (12-11)"), a numeric win-rate matrix, and a counts-only matrix ("12-11"). Diagonals show "—" in the string variants and NaN in the numeric one.

**Files:**
- Modify: `mtg_scrape/build_matchup_matrix.py`
- Modify: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_matchup_matrix.py`:

```python
from pathlib import Path
from mtg_scrape.build_matchup_matrix import render_csvs


def test_render_csvs_writes_three_files(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    assert (tmp_path / "matchup_matrix.csv").exists()
    assert (tmp_path / "matchup_matrix_numeric.csv").exists()
    assert (tmp_path / "matchup_matrix_counts.csv").exists()


def test_string_csv_cells_format_percent_and_wl(tmp_path: Path):
    # A beats B twice, loses once -> A vs B = 67% (2-1); B vs A = 33% (1-2)
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix.csv", index_col=0)
    assert df.loc["A", "B"] == "67% (2-1)"
    assert df.loc["B", "A"] == "33% (1-2)"
    # Diagonal is "—"
    assert df.loc["A", "A"] == "—"
    assert df.loc["B", "B"] == "—"


def test_counts_csv_uses_wl_string(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix_counts.csv", index_col=0)
    assert df.loc["A", "B"] == "2-1"
    assert df.loc["A", "A"] == "—"


def test_numeric_csv_has_win_rate_floats(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix_numeric.csv", index_col=0)
    assert df.loc["A", "B"] == pytest.approx(2 / 3)
    # Diagonal is NaN
    assert pd.isna(df.loc["A", "A"])


def test_empty_cell_renders_as_em_dash_in_string(tmp_path: Path):
    """A cell with 0 wins and 0 losses (never played) should render as '—', not '0% (0-0)'."""
    wins = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 0], [0, 0]], index=["A", "B"], columns=["A", "B"])

    render_csvs(wins, losses, out_dir=tmp_path)

    df = pd.read_csv(tmp_path / "matchup_matrix.csv", index_col=0)
    assert df.loc["A", "B"] == "—"
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 5 new failures.

- [ ] **Step 3: Implement `render_csvs`**

Append to `mtg_scrape/build_matchup_matrix.py`:

```python
from pathlib import Path

EM_DASH = "—"  # U+2014


def _format_cell_string(wins: int, losses: int, is_diagonal: bool) -> str:
    if is_diagonal or (wins + losses) == 0:
        return EM_DASH
    pct = round(100 * wins / (wins + losses))
    return f"{pct}% ({wins}-{losses})"


def _format_counts_string(wins: int, losses: int, is_diagonal: bool) -> str:
    if is_diagonal:
        return EM_DASH
    return f"{wins}-{losses}"


def render_csvs(wins: pd.DataFrame, losses: pd.DataFrame, out_dir: Path) -> None:
    """Emit matchup_matrix.csv, matchup_matrix_numeric.csv, and matchup_matrix_counts.csv."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = list(wins.index)
    is_diag = lambda r, c: r == c

    string_df = pd.DataFrame(
        {col: [
            _format_cell_string(int(wins.loc[row, col]), int(losses.loc[row, col]), is_diag(row, col))
            for row in labels
        ] for col in labels},
        index=labels,
    )
    counts_df = pd.DataFrame(
        {col: [
            _format_counts_string(int(wins.loc[row, col]), int(losses.loc[row, col]), is_diag(row, col))
            for row in labels
        ] for col in labels},
        index=labels,
    )
    numeric_df = compute_win_rate(wins, losses)

    string_df.to_csv(out_dir / "matchup_matrix.csv")
    numeric_df.to_csv(out_dir / "matchup_matrix_numeric.csv")
    counts_df.to_csv(out_dir / "matchup_matrix_counts.csv")
```

- [ ] **Step 4: Run, confirm all pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py
git commit -m "Render matchup matrix as three CSVs (string, numeric, counts)"
```

---

## Task 6: PNG heatmap renderer

Matplotlib heatmap with RdBu_r colormap centered at 0.5, cell annotations from the string matrix, low-sample cells visually de-emphasized.

**Files:**
- Modify: `mtg_scrape/build_matchup_matrix.py`
- Modify: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_matchup_matrix.py`:

```python
from mtg_scrape.build_matchup_matrix import render_png


def test_render_png_writes_a_non_empty_file(tmp_path: Path):
    wins = pd.DataFrame([[0, 2], [1, 0]], index=["A", "B"], columns=["A", "B"])
    losses = pd.DataFrame([[0, 1], [2, 0]], index=["A", "B"], columns=["A", "B"])

    out_path = tmp_path / "matchup_matrix.png"
    render_png(wins, losses, out_path=out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 1000  # non-trivial PNG, not a stub
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 1 new failure.

- [ ] **Step 3: Implement `render_png`**

Append to `mtg_scrape/build_matchup_matrix.py`:

```python
import matplotlib

matplotlib.use("Agg")  # no GUI; we only write files
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

LOW_SAMPLE_THRESHOLD = 5  # cells with fewer total matches are de-emphasized


def render_png(
    wins: pd.DataFrame,
    losses: pd.DataFrame,
    out_path: Path,
    low_sample_threshold: int = LOW_SAMPLE_THRESHOLD,
) -> None:
    """Render the matchup matrix as a PNG heatmap.

    Colormap: RdBu_r diverging, centered at 0.5. Cells with
    wins+losses < low_sample_threshold are rendered with reduced alpha.
    Diagonal cells are blanked (no color, em-dash label).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    labels = list(wins.index)
    n = len(labels)
    wr = compute_win_rate(wins, losses)  # NaN on diagonal and empty cells

    # Build cell label strings ("X% (W-L)" or "—") and alpha mask
    cell_text = [[""] * n for _ in range(n)]
    alpha_mask = [[1.0] * n for _ in range(n)]
    for i, row in enumerate(labels):
        for j, col in enumerate(labels):
            w = int(wins.loc[row, col])
            l = int(losses.loc[row, col])
            total = w + l
            if row == col or total == 0:
                cell_text[i][j] = EM_DASH
                alpha_mask[i][j] = 0.0  # blank diagonal
            else:
                pct = round(100 * w / total)
                cell_text[i][j] = f"{pct}% ({w}-{l})"
                if total < low_sample_threshold:
                    alpha_mask[i][j] = 0.4

    fig, ax = plt.subplots(figsize=(max(8, 0.9 * n), max(7, 0.8 * n)))
    norm = TwoSlopeNorm(vmin=0.0, vcenter=0.5, vmax=1.0)
    cmap = plt.get_cmap("RdBu_r")

    for i in range(n):
        for j in range(n):
            value = wr.iat[i, j]
            color = (1.0, 1.0, 1.0, 0.0) if pd.isna(value) else (*cmap(norm(value))[:3], alpha_mask[i][j])
            ax.add_patch(plt.Rectangle((j, n - 1 - i), 1, 1, facecolor=color, edgecolor="white"))
            ax.text(j + 0.5, n - 1 - i + 0.5, cell_text[i][j], ha="center", va="center", fontsize=8)

    ax.set_xlim(0, n)
    ax.set_ylim(0, n)
    ax.set_xticks([j + 0.5 for j in range(n)])
    ax.set_yticks([n - 1 - i + 0.5 for i in range(n)])
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Opponent archetype", fontsize=10)
    ax.set_ylabel("Row archetype's win rate vs column", fontsize=10)
    ax.set_title("PT Secrets of Strixhaven — Standard archetype matchup matrix", fontsize=11)
    ax.set_aspect("equal")
    ax.tick_params(top=False, bottom=False, left=False, right=False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.7, label="Win rate")
    cbar.set_ticks([0.0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"])

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py
git commit -m "Render matchup matrix as RdBu_r heatmap PNG"
```

---

## Task 7: End-to-end main() and smoke test

Wire everything together. `main()` reads `data/matchups.csv`, picks top 10, builds the long frame, computes the matrix, and emits all four artifacts to `data/`. A smoke test runs the full pipeline against a synthetic 3-row CSV.

**Files:**
- Modify: `mtg_scrape/build_matchup_matrix.py`
- Modify: `tests/test_build_matchup_matrix.py`

- [ ] **Step 1: Append the smoke test**

Append to `tests/test_build_matchup_matrix.py`:

```python
from mtg_scrape.build_matchup_matrix import main


def test_end_to_end_smoke_produces_all_four_files(tmp_path: Path):
    matchups_path = tmp_path / "matchups.csv"
    matchups_path.write_text(
        "match_id,round,player_a,archetype_a,elo_a_pre,elo_a_post,player_b,archetype_b,elo_b_pre,elo_b_post,result,game_score\n"
        "1,4,P1,IzzetProwess,1800,1810,P2,Mono-Green,1700,1690,W,2-1\n"
        "2,5,P3,IzzetProwess,1750,1760,P4,Mono-Green,1820,1810,W,2-0\n"
        "3,6,P5,Mono-Green,1900,1910,P6,IzzetProwess,1880,1870,W,2-1\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    main(["--matchups", str(matchups_path), "--out-dir", str(out_dir), "--top-n", "2"])

    assert (out_dir / "matchup_matrix.csv").exists()
    assert (out_dir / "matchup_matrix_numeric.csv").exists()
    assert (out_dir / "matchup_matrix_counts.csv").exists()
    assert (out_dir / "matchup_matrix.png").exists()

    # Cross-check a single cell: Izzet has 2W and 1L vs Mono-Green
    df = pd.read_csv(out_dir / "matchup_matrix.csv", index_col=0)
    assert df.loc["IzzetProwess", "Mono-Green"] == "67% (2-1)"
    assert df.loc["Mono-Green", "IzzetProwess"] == "33% (1-2)"
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 1 new failure (`main` not defined or not accepting args).

- [ ] **Step 3: Implement `main()` and wire it up**

Append to `mtg_scrape/build_matchup_matrix.py`:

```python
import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matchups", default="data/matchups.csv")
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)

    matchups = pd.read_csv(args.matchups)
    labels = top_n_archetypes(matchups, n=args.top_n) + [OTHER_LABEL]
    long = to_long_frame(matchups, top_n=labels[:-1])  # exclude OTHER from "top" arg
    wins, losses = compute_matrix(long, ordered_labels=labels)

    out_dir = Path(args.out_dir)
    render_csvs(wins, losses, out_dir=out_dir)
    render_png(wins, losses, out_path=out_dir / "matchup_matrix.png")

    print(f"Wrote matchup matrix artifacts to {out_dir}:")
    for name in ("matchup_matrix.csv", "matchup_matrix_numeric.csv",
                 "matchup_matrix_counts.csv", "matchup_matrix.png"):
        print(f"  - {name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, confirm all pass**

Run: `.venv/bin/pytest tests/test_build_matchup_matrix.py -v`
Expected: 20 passed.

Also run the full suite to confirm no regressions:

Run: `.venv/bin/pytest -v`
Expected: all tests pass (72 from prior project + 20 new = 92 expected).

- [ ] **Step 5: Run against real data**

Run: `.venv/bin/python -m mtg_scrape.build_matchup_matrix`
Expected: prints `Wrote matchup matrix artifacts to data:` followed by the 4 filenames. No errors.

Inspect `data/matchup_matrix.csv` — should be 11 rows × 11 columns (header + 10 archetypes + "Other"; index column + 10 archetypes + "Other").

Open `data/matchup_matrix.png` visually and confirm the heatmap renders sensibly: top-10 archetype labels readable, RdBu_r colormap centered at 50%, off-diagonal cells colored by win rate, diagonal blank.

- [ ] **Step 6: Commit**

```
git add mtg_scrape/build_matchup_matrix.py tests/test_build_matchup_matrix.py data/matchup_matrix.csv data/matchup_matrix_numeric.csv data/matchup_matrix_counts.csv data/matchup_matrix.png
git commit -m "End-to-end matchup matrix generator (CSVs + PNG)"
```

---

## Out of scope (deferred)

- Game-level matrix (matches only for now).
- Confidence intervals, Wilson scores, p-values.
- Interactive views.
- Time-sliced or per-player matrices.
- A CLI flag for `--min-cell-games` threshold (currently hardcoded to 5).
