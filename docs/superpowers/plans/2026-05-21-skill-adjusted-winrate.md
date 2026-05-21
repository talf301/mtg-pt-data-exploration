# Skill-Adjusted Win Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python script that computes per-archetype observed vs. Elo-expected win rates from `data/matchups.csv`, surfacing a residual that isolates "deck strength" from "pilot strength" for PT Secrets of Strixhaven.

**Architecture:** Single module (`mtg_scrape/build_skill_adjusted.py`) with small testable functions: Elo formula → filter/expand into a long frame → per-archetype aggregation → CSV + PNG renderers. Reuses `top_n_archetypes` from `build_matchup_matrix.py` for the PNG's archetype subset. Fixture-driven unit tests use synthetic DataFrames.

**Tech Stack:** Python 3.11+, pandas + matplotlib (both already dependencies), pytest.

**Source of truth:** `docs/superpowers/specs/2026-05-21-skill-adjusted-winrate-design.md`

---

## Task 1: Elo expected-probability function

The core math: mtgeloproject's formula with `b=1.5` and a 200-point reference gap giving 60% expected win rate. Pure function, no I/O.

**Files:**
- Create: `mtg_scrape/build_skill_adjusted.py`
- Create: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_build_skill_adjusted.py`:

```python
import pytest

from mtg_scrape.build_skill_adjusted import _elo_expected


def test_elo_expected_is_50pct_at_zero_gap():
    assert _elo_expected(my_elo=1800.0, opp_elo=1800.0) == pytest.approx(0.5)


def test_elo_expected_is_60pct_at_200_gap_higher():
    # The defining anchor of mtgeloproject's scale.
    assert _elo_expected(my_elo=1800.0, opp_elo=1600.0) == pytest.approx(0.6, abs=1e-6)


def test_elo_expected_is_40pct_at_200_gap_lower():
    # Symmetric mirror: my_elo 200 below opponent -> 40% win rate.
    assert _elo_expected(my_elo=1600.0, opp_elo=1800.0) == pytest.approx(0.4, abs=1e-6)


def test_elo_expected_symmetric_sums_to_1():
    # For any gap, P(A wins) + P(B wins) == 1.0
    for my, opp in [(1500, 1700), (1900, 1500), (2000, 2050)]:
        a = _elo_expected(my, opp)
        b = _elo_expected(opp, my)
        assert a + b == pytest.approx(1.0, abs=1e-9)
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `_elo_expected`**

Create `mtg_scrape/build_skill_adjusted.py`:

```python
"""Compute per-archetype observed vs Elo-expected win rates for PT Strixhaven.

mtgeloproject's Elo scale, per their FAQ:
  - Players enter at 1500.
  - 200-point gap -> 60% expected win rate.
This implies P(A wins) = 1 / (1 + 1.5 ** ((R_B - R_A) / 200)).
"""
from __future__ import annotations

import pandas as pd

ELO_BASE = 1.5      # base of the Elo exponent
ELO_SCALE = 200.0   # rating gap that corresponds to 60% win rate


def _elo_expected(my_elo: float, opp_elo: float) -> float:
    """Elo-expected win probability for a player at my_elo vs opp_elo."""
    return 1.0 / (1.0 + ELO_BASE ** ((opp_elo - my_elo) / ELO_SCALE))
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Add mtgeloproject Elo-expected win probability formula"
```

---

## Task 2: Long-frame expansion (filter + mirror perspective)

Convert each matchups row into two long-frame rows (one per perspective). Drop draws, mirrors, and NaN-Elo rows.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_skill_adjusted.py`:

```python
import pandas as pd
from mtg_scrape.build_skill_adjusted import to_skill_long_frame


def _matchups(rows):
    """Each row: (arch_a, arch_b, result, elo_a_pre, elo_b_pre)."""
    return pd.DataFrame(
        rows,
        columns=["archetype_a", "archetype_b", "result", "elo_a_pre", "elo_b_pre"],
    )


def test_long_frame_doubles_decided_non_mirror_rows():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 4  # 2 input rows × 2 perspectives, all kept


def test_long_frame_drops_draws():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("IzzetProwess", "Mono-Green", "D", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the W row's two perspectives


def test_long_frame_drops_mirrors():
    m = _matchups([
        ("IzzetProwess", "IzzetProwess", "W", 1800.0, 1700.0),
        ("IzzetProwess", "Mono-Green",   "W", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the non-mirror W row's two perspectives
    assert (long["my_arch"] == "IzzetProwess").any()
    assert (long["my_arch"] == "Mono-Green").any()


def test_long_frame_drops_rows_with_nan_elo():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, float("nan")),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
    ])
    long = to_skill_long_frame(m)
    assert len(long) == 2  # only the row with both elos present survives


def test_long_frame_mirror_perspective_flips_result_and_swaps_elos():
    m = _matchups([("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0)])
    long = to_skill_long_frame(m)
    forward = long[long["my_arch"] == "IzzetProwess"].iloc[0]
    assert forward["opp_arch"] == "Mono-Green"
    assert forward["result"] == "W"
    assert forward["my_elo"] == 1800.0
    assert forward["opp_elo"] == 1700.0
    mirror = long[long["my_arch"] == "Mono-Green"].iloc[0]
    assert mirror["opp_arch"] == "IzzetProwess"
    assert mirror["result"] == "L"
    assert mirror["my_elo"] == 1700.0
    assert mirror["opp_elo"] == 1800.0
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 5 new failures.

- [ ] **Step 3: Implement `to_skill_long_frame`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
_FLIP = {"W": "L", "L": "W"}


def to_skill_long_frame(matchups: pd.DataFrame) -> pd.DataFrame:
    """Expand each decided non-mirror match into two long-frame rows.

    Columns: my_arch, opp_arch, my_elo, opp_elo, result.

    Filters out:
      - draws (result == "D")
      - mirror matches (archetype_a == archetype_b)
      - rows missing either elo_a_pre or elo_b_pre
    """
    keep = (
        matchups["result"].isin(_FLIP)
        & (matchups["archetype_a"] != matchups["archetype_b"])
        & matchups["elo_a_pre"].notna()
        & matchups["elo_b_pre"].notna()
    )
    m = matchups[keep]

    forward = pd.DataFrame({
        "my_arch":  m["archetype_a"].to_numpy(),
        "opp_arch": m["archetype_b"].to_numpy(),
        "my_elo":   m["elo_a_pre"].to_numpy(dtype=float),
        "opp_elo":  m["elo_b_pre"].to_numpy(dtype=float),
        "result":   m["result"].to_numpy(),
    })
    mirror = pd.DataFrame({
        "my_arch":  m["archetype_b"].to_numpy(),
        "opp_arch": m["archetype_a"].to_numpy(),
        "my_elo":   m["elo_b_pre"].to_numpy(dtype=float),
        "opp_elo":  m["elo_a_pre"].to_numpy(dtype=float),
        "result":   m["result"].map(_FLIP).to_numpy(),
    })
    return pd.concat([forward, mirror], ignore_index=True)
```

- [ ] **Step 4: Run, confirm all pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Expand matchups into skill long-frame, drop mirrors and draws"
```

---

## Task 3: Per-archetype summary (observed + expected)

Aggregate the long-frame into one row per archetype: observed wins/losses, expected wins/losses, observed/expected win rates, residual.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_skill_adjusted.py`:

```python
from mtg_scrape.build_skill_adjusted import compute_archetype_summary


def test_summary_has_one_row_per_archetype():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long)
    assert set(summary["archetype"]) == {"IzzetProwess", "Mono-Green"}


def test_summary_observed_counts():
    # Izzet wins both. Each match contributes 1 observed W for Izzet, 1 L for Mono-Green.
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1700.0),
        ("Mono-Green",   "IzzetProwess", "L", 1750.0, 1850.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    assert int(summary.loc["IzzetProwess", "observed_wins"]) == 2
    assert int(summary.loc["IzzetProwess", "observed_losses"]) == 0
    assert int(summary.loc["Mono-Green", "observed_wins"]) == 0
    assert int(summary.loc["Mono-Green", "observed_losses"]) == 2


def test_summary_expected_counts_at_tied_elo_match_observed():
    """At zero Elo gap, expected = observed for each side."""
    # 2 matches, both tied Elo (1800 vs 1800). Izzet wins both.
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    # Each side expected 1 win and 1 loss across 2 matches at 50% expectation each
    assert summary.loc["IzzetProwess", "expected_wins"] == pytest.approx(1.0)
    assert summary.loc["IzzetProwess", "expected_losses"] == pytest.approx(1.0)
    assert summary.loc["Mono-Green", "expected_wins"] == pytest.approx(1.0)
    assert summary.loc["Mono-Green", "expected_losses"] == pytest.approx(1.0)


def test_summary_residual_is_observed_minus_expected_winrate():
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
        ("IzzetProwess", "Mono-Green", "W", 1800.0, 1800.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    # Izzet observed 2-0 (100%), expected 50% -> residual +0.5
    assert summary.loc["IzzetProwess", "observed_wr"] == pytest.approx(1.0)
    assert summary.loc["IzzetProwess", "expected_wr"] == pytest.approx(0.5)
    assert summary.loc["IzzetProwess", "residual"] == pytest.approx(0.5)


def test_summary_zero_sum_invariant():
    """Sum of observed wins == sum of observed losses == sum of expected wins == sum of expected losses."""
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1850.0, 1700.0),
        ("IzzetProwess", "Mono-Green", "L", 1700.0, 1850.0),
        ("Selesnya",     "IzzetProwess", "W", 1750.0, 1750.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long)
    total_obs_w = summary["observed_wins"].sum()
    total_obs_l = summary["observed_losses"].sum()
    total_exp_w = summary["expected_wins"].sum()
    total_exp_l = summary["expected_losses"].sum()
    assert total_obs_w == total_obs_l == pytest.approx(total_exp_w) == pytest.approx(total_exp_l)


def test_summary_overperforming_deck_has_positive_residual():
    """A deck piloted by lower-Elo players that wins more than expected should have a positive residual."""
    # Izzet at 1500 always beats Mono-Green at 1900 (huge skill gap, but Izzet wins all 3).
    m = _matchups([
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
        ("IzzetProwess", "Mono-Green", "W", 1500.0, 1900.0),
    ])
    long = to_skill_long_frame(m)
    summary = compute_archetype_summary(long).set_index("archetype")
    assert summary.loc["IzzetProwess", "residual"] > 0.5  # observed 100%, expected ~14%
    assert summary.loc["Mono-Green", "residual"] < -0.5
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 6 new failures.

- [ ] **Step 3: Implement `compute_archetype_summary`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
def compute_archetype_summary(long: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the long-frame into one row per archetype.

    Output columns:
      archetype, games, observed_wins, observed_losses, observed_wr,
      expected_wins, expected_losses, expected_wr, residual
    """
    if long.empty:
        return pd.DataFrame(columns=[
            "archetype", "games",
            "observed_wins", "observed_losses", "observed_wr",
            "expected_wins", "expected_losses", "expected_wr",
            "residual",
        ])

    work = long.copy()
    work["p_win"] = work.apply(
        lambda r: _elo_expected(r["my_elo"], r["opp_elo"]),
        axis=1,
    )
    work["obs_w"] = (work["result"] == "W").astype(int)
    work["obs_l"] = (work["result"] == "L").astype(int)
    work["exp_w"] = work["p_win"]
    work["exp_l"] = 1.0 - work["p_win"]

    grouped = work.groupby("my_arch").agg(
        games=("result", "size"),
        observed_wins=("obs_w", "sum"),
        observed_losses=("obs_l", "sum"),
        expected_wins=("exp_w", "sum"),
        expected_losses=("exp_l", "sum"),
    ).reset_index().rename(columns={"my_arch": "archetype"})

    grouped["observed_wr"] = grouped["observed_wins"] / grouped["games"]
    grouped["expected_wr"] = grouped["expected_wins"] / grouped["games"]
    grouped["residual"] = grouped["observed_wr"] - grouped["expected_wr"]

    return grouped[[
        "archetype", "games",
        "observed_wins", "observed_losses", "observed_wr",
        "expected_wins", "expected_losses", "expected_wr",
        "residual",
    ]]
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Aggregate per-archetype observed vs Elo-expected win rates"
```

---

## Task 4: CSV renderer

Write the full 32-archetype summary to `data/archetype_skill_adjusted.csv` sorted by residual desc.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_skill_adjusted.py`:

```python
from pathlib import Path
from mtg_scrape.build_skill_adjusted import render_csv


def test_render_csv_writes_file_sorted_by_residual_desc(tmp_path: Path):
    summary = pd.DataFrame([
        {"archetype": "A", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 4.0, "expected_losses": 6.0,
         "expected_wr": 0.4, "residual": 0.10},
        {"archetype": "B", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 6.0, "expected_losses": 4.0,
         "expected_wr": 0.6, "residual": -0.10},
        {"archetype": "C", "games": 10, "observed_wins": 5, "observed_losses": 5,
         "observed_wr": 0.5, "expected_wins": 5.0, "expected_losses": 5.0,
         "expected_wr": 0.5, "residual": 0.0},
    ])
    out = tmp_path / "archetype_skill_adjusted.csv"
    render_csv(summary, out)
    assert out.exists()
    df = pd.read_csv(out)
    # Sorted by residual descending: A (+0.10), C (0.0), B (-0.10)
    assert list(df["archetype"]) == ["A", "C", "B"]


def test_render_csv_preserves_all_columns(tmp_path: Path):
    summary = pd.DataFrame([{
        "archetype": "A", "games": 10, "observed_wins": 5, "observed_losses": 5,
        "observed_wr": 0.5, "expected_wins": 4.0, "expected_losses": 6.0,
        "expected_wr": 0.4, "residual": 0.10,
    }])
    out = tmp_path / "summary.csv"
    render_csv(summary, out)
    df = pd.read_csv(out)
    expected_cols = ["archetype", "games", "observed_wins", "observed_losses",
                     "observed_wr", "expected_wins", "expected_losses",
                     "expected_wr", "residual"]
    assert list(df.columns) == expected_cols
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Implement `render_csv`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
from pathlib import Path


def render_csv(summary: pd.DataFrame, out_path: Path) -> None:
    """Write the summary DataFrame to CSV, sorted by residual descending."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary.sort_values("residual", ascending=False).to_csv(out_path, index=False)
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Render archetype skill-adjusted summary as CSV"
```

---

## Task 5: PNG bar chart (top-10 + Other)

Paired horizontal bars (observed, expected) per archetype in the top-10-plus-Other subset, sorted by residual desc, with residual annotated at the right edge and sample size in the y-tick label.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_build_skill_adjusted.py`:

```python
from mtg_scrape.build_skill_adjusted import render_png


def test_render_png_writes_a_non_empty_file(tmp_path: Path):
    summary = pd.DataFrame([
        {"archetype": "A", "games": 100, "observed_wins": 60, "observed_losses": 40,
         "observed_wr": 0.60, "expected_wins": 55.0, "expected_losses": 45.0,
         "expected_wr": 0.55, "residual": 0.05},
        {"archetype": "B", "games": 100, "observed_wins": 40, "observed_losses": 60,
         "observed_wr": 0.40, "expected_wins": 45.0, "expected_losses": 55.0,
         "expected_wr": 0.45, "residual": -0.05},
    ])
    out_path = tmp_path / "archetype_skill_adjusted.png"
    render_png(summary, archetypes=["A", "B"], out_path=out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 1000
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 1 new failure.

- [ ] **Step 3: Implement `render_png`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
import matplotlib

matplotlib.use("Agg")  # no GUI
import matplotlib.pyplot as plt


def render_png(
    summary: pd.DataFrame,
    archetypes: list[str],
    out_path: Path,
) -> None:
    """Paired horizontal bars (expected, observed) per archetype, sorted by residual desc.

    Only renders archetypes in the provided list (typically top-10 + Other).
    Reference line at 50%. Residual annotated at the right end of each pair.
    Y-tick label shows archetype name with sample size: 'Izzet Prowess (n=719)'.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    subset = summary[summary["archetype"].isin(archetypes)].copy()
    subset = subset[subset["games"] > 0]  # skip empties
    subset = subset.sort_values("residual", ascending=False).reset_index(drop=True)

    n = len(subset)
    if n == 0:
        # Defensive: empty plot
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(10, max(4, 0.6 * n + 1)))

    bar_h = 0.35
    y = list(range(n))
    expected = subset["expected_wr"].to_numpy()
    observed = subset["observed_wr"].to_numpy()
    residual = subset["residual"].to_numpy()

    # Top bars: expected (lighter); bottom bars: observed (darker)
    ax.barh([yi + bar_h / 2 for yi in y], expected, height=bar_h,
            color="#a5b4d1", label="Expected (Elo)")
    ax.barh([yi - bar_h / 2 for yi in y], observed, height=bar_h,
            color="#3b5998", label="Observed")

    # Reference line at 50%
    ax.axvline(0.5, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)

    # Residual annotation at the right end of each archetype
    x_text = max(expected.max(), observed.max()) + 0.03
    for yi, r in zip(y, residual):
        sign = "+" if r >= 0 else ""
        color = "#1a7a1a" if r >= 0 else "#a01515"
        ax.text(x_text, yi, f"{sign}{r * 100:.1f}%", va="center", color=color, fontsize=9, weight="bold")

    # Y-axis labels: "archetype (n=games)"
    labels = [f"{row.archetype} (n={int(row.games)})" for row in subset.itertuples()]
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # highest residual at top

    ax.set_xlim(0, x_text + 0.08)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Win rate")
    ax.set_title("PT Secrets of Strixhaven — observed vs Elo-expected win rate")
    ax.legend(loc="lower right", framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Render skill-adjusted summary as PNG bar chart"
```

---

## Task 6: Zero-sum invariant assertion

A small runtime check that the per-archetype summary's expected and observed totals are zero-sum. Spec promised this; lock it in.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_build_skill_adjusted.py`:

```python
from mtg_scrape.build_skill_adjusted import _assert_zero_sum


def test_assert_zero_sum_passes_on_consistent_summary():
    summary = pd.DataFrame([
        {"archetype": "A", "games": 10, "observed_wins": 6, "observed_losses": 4,
         "observed_wr": 0.6, "expected_wins": 5.5, "expected_losses": 4.5,
         "expected_wr": 0.55, "residual": 0.05},
        {"archetype": "B", "games": 10, "observed_wins": 4, "observed_losses": 6,
         "observed_wr": 0.4, "expected_wins": 4.5, "expected_losses": 5.5,
         "expected_wr": 0.45, "residual": -0.05},
    ])
    _assert_zero_sum(summary)  # 6+4 == 4+6 observed; 5.5+4.5 == 4.5+5.5 expected


def test_assert_zero_sum_raises_on_inconsistent_summary():
    # Total observed wins = 7 but losses = 4 -> mismatch
    summary = pd.DataFrame([
        {"archetype": "A", "games": 10, "observed_wins": 7, "observed_losses": 3,
         "observed_wr": 0.7, "expected_wins": 5.0, "expected_losses": 5.0,
         "expected_wr": 0.5, "residual": 0.2},
        {"archetype": "B", "games": 10, "observed_wins": 0, "observed_losses": 1,
         "observed_wr": 0.0, "expected_wins": 5.0, "expected_losses": 5.0,
         "expected_wr": 0.5, "residual": -0.5},
    ])
    with pytest.raises(AssertionError, match="zero-sum"):
        _assert_zero_sum(summary)
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 2 new failures.

- [ ] **Step 3: Implement `_assert_zero_sum`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
def _assert_zero_sum(summary: pd.DataFrame) -> None:
    """Total observed wins must equal total observed losses, ditto for expected.

    Every long-frame row contributes one win to one archetype and one loss to
    another (or one expected-win and one expected-loss). Imbalance signals a
    bug in the long-frame construction or the aggregation.
    """
    import math

    obs_w = int(summary["observed_wins"].sum())
    obs_l = int(summary["observed_losses"].sum())
    exp_w = float(summary["expected_wins"].sum())
    exp_l = float(summary["expected_losses"].sum())

    assert obs_w == obs_l, f"observed not zero-sum: wins={obs_w}, losses={obs_l}"
    assert math.isclose(exp_w, exp_l, abs_tol=1e-6), (
        f"expected not zero-sum: wins={exp_w}, losses={exp_l}"
    )
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 20 passed.

- [ ] **Step 5: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py
git commit -m "Assert per-archetype summary is zero-sum at runtime"
```

---

## Task 7: End-to-end main() + smoke + real-data run

Wire it all up. `main()` reads `data/matchups.csv`, computes the summary, asserts zero-sum, writes both artifacts.

**Files:**
- Modify: `mtg_scrape/build_skill_adjusted.py`
- Modify: `tests/test_build_skill_adjusted.py`

- [ ] **Step 1: Append the smoke test**

Append to `tests/test_build_skill_adjusted.py`:

```python
from mtg_scrape.build_skill_adjusted import main


def test_end_to_end_smoke_produces_both_artifacts(tmp_path: Path):
    matchups_path = tmp_path / "matchups.csv"
    matchups_path.write_text(
        "match_id,round,player_a,archetype_a,elo_a_pre,elo_a_post,player_b,archetype_b,elo_b_pre,elo_b_post,result,game_score\n"
        "1,4,P1,IzzetProwess,1800,1810,P2,Mono-Green,1700,1690,W,2-1\n"
        "2,5,P3,IzzetProwess,1750,1760,P4,Mono-Green,1820,1810,W,2-0\n"
        "3,6,P5,Mono-Green,1900,1910,P6,IzzetProwess,1880,1870,W,2-1\n"
        "4,7,P7,Selesnya,1700,1710,P8,IzzetProwess,1750,1740,W,2-0\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    main([
        "--matchups", str(matchups_path),
        "--out-dir", str(out_dir),
        "--top-n", "2",
    ])

    assert (out_dir / "archetype_skill_adjusted.csv").exists()
    assert (out_dir / "archetype_skill_adjusted.png").exists()

    df = pd.read_csv(out_dir / "archetype_skill_adjusted.csv")
    assert set(df["archetype"]) == {"IzzetProwess", "Mono-Green", "Selesnya"}
    # Sorted by residual desc
    assert df.iloc[0]["residual"] >= df.iloc[-1]["residual"]
```

- [ ] **Step 2: Run, confirm fails**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 1 new failure (`main` not defined).

- [ ] **Step 3: Implement `main()`**

Append to `mtg_scrape/build_skill_adjusted.py`:

```python
import argparse

from mtg_scrape.build_matchup_matrix import OTHER_LABEL, top_n_archetypes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matchups", default="data/matchups.csv")
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)

    matchups = pd.read_csv(args.matchups)
    long = to_skill_long_frame(matchups)
    summary = compute_archetype_summary(long)
    _assert_zero_sum(summary)

    # Pick the archetype subset for the PNG: top-N by appearance in matchups,
    # plus an "Other" bucket if any archetype outside the top-N has games.
    top = top_n_archetypes(matchups, n=args.top_n)
    png_subset = list(top)
    # If the summary contains any archetypes outside top-N, also include "Other"
    # via post-hoc relabeling in a separate working copy.
    extra_mask = ~summary["archetype"].isin(top)
    if extra_mask.any():
        # Aggregate the long-tail into a single "Other" row for the PNG
        other_summary = _aggregate_into_other(summary, extra_mask, top)
        png_summary = pd.concat([summary[~extra_mask], other_summary], ignore_index=True)
        png_subset = list(top) + [OTHER_LABEL]
    else:
        png_summary = summary

    out_dir = Path(args.out_dir)
    render_csv(summary, out_dir / "archetype_skill_adjusted.csv")
    render_png(png_summary, archetypes=png_subset, out_path=out_dir / "archetype_skill_adjusted.png")

    print(f"Wrote skill-adjusted artifacts to {out_dir}:")
    print(f"  - archetype_skill_adjusted.csv  ({len(summary)} archetypes)")
    print(f"  - archetype_skill_adjusted.png  (top-{args.top_n} + {OTHER_LABEL})")


def _aggregate_into_other(summary: pd.DataFrame, mask: pd.Series, top: list[str]) -> pd.DataFrame:
    """Collapse the rows in `summary[mask]` into a single 'Other' row."""
    rest = summary[mask]
    games = int(rest["games"].sum())
    obs_w = int(rest["observed_wins"].sum())
    obs_l = int(rest["observed_losses"].sum())
    exp_w = float(rest["expected_wins"].sum())
    exp_l = float(rest["expected_losses"].sum())
    if games == 0:
        return pd.DataFrame()
    obs_wr = obs_w / games
    exp_wr = exp_w / games
    return pd.DataFrame([{
        "archetype": OTHER_LABEL,
        "games": games,
        "observed_wins": obs_w,
        "observed_losses": obs_l,
        "observed_wr": obs_wr,
        "expected_wins": exp_w,
        "expected_losses": exp_l,
        "expected_wr": exp_wr,
        "residual": obs_wr - exp_wr,
    }])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, confirm pass**

Run: `.venv/bin/pytest tests/test_build_skill_adjusted.py -v`
Expected: 21 passed.

Also run the full suite to confirm no regressions:

Run: `.venv/bin/pytest -v`
Expected: 121 passed (100 prior + 21 new).

- [ ] **Step 5: Run against real data**

Run: `.venv/bin/python -m mtg_scrape.build_skill_adjusted`
Expected: prints "Wrote skill-adjusted artifacts to data:" followed by the two filenames. No errors.

Quick sanity check:

```
.venv/bin/python -c "
import pandas as pd
df = pd.read_csv('data/archetype_skill_adjusted.csv')
print('Total archetypes:', len(df))
print()
print(df.head(10).to_string(index=False))
"
```

Confirm: ~30 archetypes, residuals make sense (probably small for top decks, larger swings for low-sample ones).

- [ ] **Step 6: Commit**

```
git add mtg_scrape/build_skill_adjusted.py tests/test_build_skill_adjusted.py data/archetype_skill_adjusted.csv data/archetype_skill_adjusted.png
git commit -m "End-to-end skill-adjusted win rate generator (CSV + PNG)"
```

---

## Out of scope (deferred)

- Confidence intervals or significance tests on the residual.
- Per-matchup expected win rates (only per-archetype overall).
- Cross-PT comparisons.
- Adjusting for opponent deck quality (the residual integrates over all opposing decks; per-matchup adjustment is a separate analysis).
