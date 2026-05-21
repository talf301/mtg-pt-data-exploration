# Skill-adjusted archetype win rate — design

**Date:** 2026-05-21
**Status:** Approved by user, ready for implementation planning
**Input:** `data/matchups.csv` (1240 PT Strixhaven Standard matches)

## Goal

For each archetype, compute the win rate it would have had if every match resolved according to mtgeloproject's Elo-based prediction. Compare to the observed win rate. The gap (residual) isolates "the deck did the work" from "the pilots did the work": positive residual means the archetype outperformed its pilots' ratings; negative means it underperformed.

## Source data

`data/matchups.csv` columns used:

| column | type | notes |
|---|---|---|
| `archetype_a`, `archetype_b` | str | magic.gg archetype labels |
| `elo_a_pre`, `elo_b_pre` | float | pre-match Elo (mtgeloproject scale); 100% populated in the dataset |
| `result` | str | `"W"`/`"L"`/`"D"` from player_a's perspective |

## Outputs

Both under `data/`:

| file | content |
|---|---|
| `archetype_skill_adjusted.csv` | One row per archetype, all 32. Columns: `archetype, games, observed_wins, observed_losses, observed_wr, expected_wins, expected_losses, expected_wr, residual`. Sorted by `residual` desc. |
| `archetype_skill_adjusted.png` | Horizontal grouped bar chart for top-10 + Other (paired expected/observed bars per archetype, sorted by residual desc, reference line at 50%, residual annotated at the right end, sample size in the y-axis label). |

`residual = observed_wr - expected_wr`. Positive → deck outperformed; negative → deck underperformed.

## Algorithm

```
1. Load matchups.csv. Filter out:
   - draws (result == "D")
   - mirror matches (archetype_a == archetype_b)
   - rows with NaN elo_a_pre OR NaN elo_b_pre (defensive; shouldn't occur
     since Task 8's opp_data.start fill ensures pre-Elos are populated)

2. Long-frame expansion. For each surviving match, emit two rows
   (one per perspective): my_arch, opp_arch, my_elo, opp_elo, result.
   The mirror row flips result W↔L and swaps the two elo values.

3. For each long-frame row, compute the Elo-expected win probability:
       p_win = 1 / (1 + 1.5 ** ((opp_elo - my_elo) / 200))
   Add p_win to that archetype's expected_wins running total;
   add (1 - p_win) to expected_losses.

4. Observed counts: result == "W" → +1 observed_win for that archetype;
   result == "L" → +1 observed_loss.

5. Per-archetype row: games = observed_wins + observed_losses;
   observed_wr = observed_wins / games;
   expected_wr = expected_wins / games (same denominator since expected
   wins + expected losses = games);
   residual = observed_wr - expected_wr.

6. Emit CSV (all 32 archetypes). Emit PNG (top-10 + Other only).
```

The mtgeloproject Elo scale uses `b = 1.5` and a 200-point reference gap to give 60% expected win rate, per the site's FAQ.

## Invariants

- **Zero-sum expectations:** `sum(expected_wins across all archetypes) == sum(observed_wins across all archetypes)` (both equal the count of decided non-mirror long-frame rows). Same for losses. The script asserts this — Elo expectations are zero-sum by construction.
- **Bounded:** `observed_wr ∈ [0, 1]` and `expected_wr ∈ [0, 1]` for every archetype with at least one game.

## Components

- `mtg_scrape/build_skill_adjusted.py` — single module:
  - `_elo_expected(my_elo, opp_elo) -> float` — the mtgeloproject formula
  - `to_skill_long_frame(matchups) -> pd.DataFrame` — filter + expand + drop mirrors and NaN-Elo rows
  - `compute_archetype_summary(long) -> pd.DataFrame` — per-archetype aggregations
  - `render_csv(summary, out_path)` — full 32-archetype CSV sorted by residual
  - `render_png(summary, archetype_subset, out_path)` — bar chart for top-10 + Other
  - `main()` — CLI glue

- Reuses `top_n_archetypes` from `mtg_scrape/build_matchup_matrix.py` to identify the PNG's archetype subset.

- `tests/test_build_skill_adjusted.py`:
  - `_elo_expected` returns 0.5 at zero gap, 0.6 at 200-point gap (calibration check on the formula constant)
  - `to_skill_long_frame` drops mirrors and draws and NaN-Elo rows; doubles row count for surviving matches
  - `compute_archetype_summary` zero-sum invariant
  - Synthetic-data residual sign check: rig a small dataset where a deck is piloted by lower-Elo players but wins disproportionately; assert positive residual
  - Smoke test: full pipeline against a synthetic 3-row CSV produces both artifacts

## File layout

```
mtg-pt-data-exploration/
├── mtg_scrape/build_skill_adjusted.py             (new)
├── tests/test_build_skill_adjusted.py             (new)
├── data/archetype_skill_adjusted.csv              (new, generated)
└── data/archetype_skill_adjusted.png              (new, generated)
```

No new third-party dependencies (matplotlib + pandas already available).

## Error handling

- Empty or missing `data/matchups.csv` → propagate pandas' `FileNotFoundError` unchanged.
- An archetype that appears only in mirrors or draws → drops out of the output (0 games after filtering). Not an error; just absent.
- Any archetype with NaN-Elo in every appearance → drops out for the same reason.

## Out of scope (explicit)

- Confidence intervals or significance tests on the residual (would need bootstrap or analytic CIs; defer).
- Per-matchup (cell-level) expected win rates. This is per-archetype overall only.
- Cross-PT comparisons. Single PT only.
- Adjusting for opponent archetype quality (i.e., not just opponent skill but their deck). The residual already integrates over the field of opposing decks; teasing apart skill-vs-deck for opponents is a separate analysis.
