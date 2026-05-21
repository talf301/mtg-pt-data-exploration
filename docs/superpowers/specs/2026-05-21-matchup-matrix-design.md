# Archetype matchup matrix — design

**Date:** 2026-05-21
**Status:** Approved by user, ready for implementation planning
**Input:** `data/matchups.csv` (1240 PT Strixhaven Standard matches)

## Goal

Produce a static archetype-vs-archetype matchup matrix for PT Secrets of Strixhaven. Output one heatmap PNG and three CSVs (human-readable, numeric, counts) covering the top-10 most-played archetypes plus an "Other" bucket. Each cell shows the row archetype's match-level win rate and the wins-losses split against the column archetype.

## Scope

- Constructed (Standard) matches only — `matchups.csv` is already filtered to these.
- Match-level outcomes (not game-level). Game scores like 2-1 vs 2-0 are not distinguished.
- One pass; one output set. No interactive UI, no notebook, no parameter sweeps.

## Source data

`data/matchups.csv` columns (relevant subset):

| column | type | notes |
|---|---|---|
| `archetype_a` | str | magic.gg label for player_a's deck |
| `archetype_b` | str | magic.gg label for player_b's deck |
| `result` | str | `"W"`, `"L"`, or `"D"` from player_a's perspective |

There are 32 distinct archetypes in the data with a heavy-tail distribution: the top 10 cover ~85% of player-rounds; 18 archetypes have fewer than 30 appearances each.

## Outputs

All under `data/`:

| file | type | content |
|---|---|---|
| `matchup_matrix.csv` | 11×11 strings | Each cell is `"53% (12-11)"`; diagonal is `"—"` |
| `matchup_matrix_numeric.csv` | 11×11 floats | Win rate per cell (0.0–1.0); diagonal NaN |
| `matchup_matrix_counts.csv` | 11×11 strings | Each cell is `"12-11"`; diagonal `"—"` |
| `matchup_matrix.png` | image | RdBu_r heatmap centered at 0.5, cells annotated with the string from `matchup_matrix.csv` |

Rows and columns are labeled by archetype. "Other" is the 11th label, aggregating the 22 sub-top-10 archetypes.

Each output also carries a rightmost **"Total"** column showing each archetype's overall record across all opponents (including mirror matches). Same cell format as the matrix proper (`"52% (374-345)"` in the string CSV; float win rate in the numeric CSV; `"374-345"` in the counts CSV; colored cell with annotation in the PNG, visually offset from the main matrix by a small gap). Useful for cross-checking row totals against published reference tallies.

## Algorithm

```
1. Load matchups.csv.

2. Compute archetype appearances: count each occurrence in archetype_a and
   archetype_b columns. Sort desc; take the top 10. Build a mapping
   {archetype -> archetype or "Other"} for all 32 source archetypes.

3. Build a "long" frame with one row per (match, perspective) — two rows per
   input row. Each long-frame row has columns:
       my_arch:  the player's archetype, mapped to top-10-or-"Other"
       opp_arch: the opponent's archetype, mapped likewise
       result:   "W" / "L" (drop draws)

4. For each (my_arch, opp_arch) pair, count wins and losses. Compute
   win_rate = wins / (wins + losses).

5. Diagonal cells (my_arch == opp_arch): set win_rate to NaN. Mirror matches
   contribute equally to the cell's wins and losses, so mathematically the
   value is always 50%, but that's not informative.

6. Emit the three CSVs and the heatmap PNG.
```

### Long-frame construction

Each input row (Izzet Prowess vs Mono-Green Landfall, Izzet won 2-1) becomes:

| my_arch | opp_arch | result |
|---|---|---|
| Izzet Prowess | Mono-Green Landfall | W |
| Mono-Green Landfall | Izzet Prowess | L |

So a 1240-row input expands to a 2480-row long frame (minus a handful of dropped draws). Each input match contributes one win to one cell and one loss to its mirror cell.

### Invariants

- For all off-diagonal pairs `(A, B)`, `win_rate(A, B) + win_rate(B, A) == 1.0` (modulo draws). The implementation asserts this.
- For any cell, `wins + losses` equals the number of matches between those two archetypes (counted twice across the matrix — once in `(A, B)`, once in `(B, A)`).
- Total wins across all off-diagonal cells equals total losses (every win has a matching loss on the other side).

### Low-sample handling

Cells with `wins + losses < 5` are visually de-emphasized in the PNG (alpha=0.4 on the colormap). The CSVs write the raw numbers regardless. The number 5 is the threshold below which any percentage is essentially noise; pick a higher threshold later by re-running with a `--min-cell-games` flag if needed.

## Components

- `mtg_scrape/build_matchup_matrix.py` — single script. Functions:
  - `load_matchups(path) -> pd.DataFrame`
  - `top_n_archetypes(matchups, n=10) -> list[str]` — by total appearances across both sides
  - `to_long_frame(matchups, top_n, other_label="Other") -> pd.DataFrame`
  - `compute_matrix(long_frame, ordered_labels) -> tuple[wins_df, losses_df]` — returns two square DataFrames
  - `render_csvs(wins, losses, out_dir)` — emits the three CSVs
  - `render_png(win_rate, counts_str, low_sample_mask, out_path)` — emits the heatmap
  - `main()` — argparse + glue

- `tests/test_build_matchup_matrix.py` — fixture-style synthetic frames covering: long-frame construction, symmetry invariant, diagonal suppression, the top-N + Other bucketing.

## File layout

```
mtg-pt-data-exploration/
├── mtg_scrape/build_matchup_matrix.py        (new)
├── tests/test_build_matchup_matrix.py        (new)
├── data/matchup_matrix.csv                   (new, generated)
├── data/matchup_matrix_numeric.csv           (new, generated)
├── data/matchup_matrix_counts.csv            (new, generated)
└── data/matchup_matrix.png                   (new, generated)
```

`pyproject.toml` already lists `pandas`; add `matplotlib` as a new dependency for the heatmap.

## Testing

- **Unit tests**, fixture-driven:
  - `to_long_frame` doubles the row count and flips result correctly for the mirror row.
  - `to_long_frame` maps sub-top-N archetypes to "Other".
  - `compute_matrix` produces a square frame with the expected wins/losses for a small hand-checked input.
  - Symmetry: for off-diagonal `(A, B)`, `wins(A,B) == losses(B,A)`.
  - Diagonal suppression: a synthetic mirror match (X vs X) doesn't produce a non-NaN diagonal.

- **Smoke test:** `python -m mtg_scrape.build_matchup_matrix` produces all 4 output files; PNG is non-zero size; CSVs have the expected 12×12 shape (11 data + 1 header row, 11 data + 1 index column).

## Error handling

- Empty or missing `data/matchups.csv` → raise FileNotFoundError with a clear message pointing at the upstream pipeline.
- Draws in the data → silently dropped (very rare; ≤2 across the event); printed count for visibility.
- `Other` bucket ending up empty (i.e., the 11-label matrix has only 10 actual labels) → still emit it; the row/column will just be NaN.

## Out of scope (explicit)

- Game-level matchup matrix (only match-level for this iteration).
- Confidence intervals, Wilson scores, p-values (cell color + sample count is the chosen rigor level).
- Interactive views (Plotly, Bokeh, notebook widgets).
- Time-sliced views (e.g., Day 1 vs Day 2 matchups).
- Cross-PT comparison (only one PT in the dataset).
- Per-player matchup data (player skill confounds aren't modeled here).
