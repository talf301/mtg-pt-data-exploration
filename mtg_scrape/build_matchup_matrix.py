"""Compute the PT Strixhaven archetype matchup matrix and render CSVs + PNG."""
from __future__ import annotations

import pandas as pd

OTHER_LABEL = "Other"


def top_n_archetypes(matchups: pd.DataFrame, n: int = 10) -> list[str]:
    """Return the n most-played archetypes, by total appearances across both sides.

    Ties broken alphabetically.
    """
    counts = pd.concat([matchups["archetype_a"], matchups["archetype_b"]]).value_counts()
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
    wr = wins.where(total > 0).astype(float).div(total.where(total > 0))
    for label in wr.index:
        if label in wr.columns:
            wr.loc[label, label] = float("nan")
    return wr


def _assert_symmetric(wins: pd.DataFrame, losses: pd.DataFrame) -> None:
    """Runtime invariant check: every off-diagonal pair (A,B) and (B,A) is consistent.

    By construction, the wins-at-(A,B) cell equals losses-at-(B,A); raise AssertionError if not.
    Diagonal cells are unconstrained and ignored.
    """
    labels = list(wins.index)
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if i == j:
                continue
            w_ab = int(wins.loc[a, b])
            l_ba = int(losses.loc[b, a])
            assert w_ab == l_ba, (
                f"matchup-matrix symmetry violated for ({a}, {b}): "
                f"wins[{a},{b}]={w_ab} but losses[{b},{a}]={l_ba}"
            )


def compute_overall(
    wins: pd.DataFrame, losses: pd.DataFrame
) -> tuple[pd.Series, pd.Series]:
    """Sum each archetype's wins and losses across all opponents.

    Mirror matches on the diagonal ARE included: each mirror contributes 1 W
    and 1 L to the archetype's totals, leaving the per-archetype win rate
    unchanged but inflating the games-played count to reflect every game
    that archetype played.
    """
    overall_wins = wins.sum(axis=1).astype(int)
    overall_losses = losses.sum(axis=1).astype(int)
    return overall_wins, overall_losses


from pathlib import Path

EM_DASH = "—"  # U+2014
TOTAL_LABEL = "Total"


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
    """Emit matchup_matrix.csv, matchup_matrix_numeric.csv, and matchup_matrix_counts.csv.

    Each output gains a rightmost "Total" column carrying per-archetype overall
    record across all opponents (mirrors included).
    """
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

    overall_wins, overall_losses = compute_overall(wins, losses)
    overall_total = overall_wins + overall_losses

    string_df[TOTAL_LABEL] = [
        _format_cell_string(int(overall_wins.loc[r]), int(overall_losses.loc[r]), is_diagonal=False)
        for r in labels
    ]
    counts_df[TOTAL_LABEL] = [
        _format_counts_string(int(overall_wins.loc[r]), int(overall_losses.loc[r]), is_diagonal=False)
        for r in labels
    ]
    numeric_df[TOTAL_LABEL] = overall_wins.astype(float).div(overall_total.where(overall_total > 0))

    string_df.to_csv(out_dir / "matchup_matrix.csv")
    numeric_df.to_csv(out_dir / "matchup_matrix_numeric.csv")
    counts_df.to_csv(out_dir / "matchup_matrix_counts.csv")


import matplotlib

matplotlib.use("Agg")  # no GUI; we only write files
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

LOW_SAMPLE_THRESHOLD = 5  # cells with fewer total matches are de-emphasized
TOTAL_COL_GAP = 0.3       # whitespace between matrix proper and the Total column


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
    A rightmost "Total" column shows each archetype's overall record, offset
    from the main matrix by a small whitespace gap.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    labels = list(wins.index)
    n = len(labels)
    wr = compute_win_rate(wins, losses)  # NaN on diagonal and empty cells
    overall_wins, overall_losses = compute_overall(wins, losses)

    # Build cell label strings and alpha mask
    cell_text = [[""] * n for _ in range(n)]
    alpha_mask = [[1.0] * n for _ in range(n)]
    for i, row in enumerate(labels):
        for j, col in enumerate(labels):
            w = int(wins.loc[row, col])
            l = int(losses.loc[row, col])
            total = w + l
            if row == col or total == 0:
                cell_text[i][j] = EM_DASH
                alpha_mask[i][j] = 0.0  # blank diagonal/empty
            else:
                pct = round(100 * w / total)
                cell_text[i][j] = f"{pct}% ({w}-{l})"
                if total < low_sample_threshold:
                    alpha_mask[i][j] = 0.4

    total_col_left = n + TOTAL_COL_GAP

    fig, ax = plt.subplots(figsize=(max(8, 0.9 * (n + 1)), max(7, 0.8 * n)))
    norm = TwoSlopeNorm(vmin=0.0, vcenter=0.5, vmax=1.0)
    cmap = plt.get_cmap("RdBu_r")

    for i in range(n):
        for j in range(n):
            value = wr.iat[i, j]
            color = (1.0, 1.0, 1.0, 0.0) if pd.isna(value) else (*cmap(norm(value))[:3], alpha_mask[i][j])
            ax.add_patch(plt.Rectangle((j, n - 1 - i), 1, 1, facecolor=color, edgecolor="white"))
            ax.text(j + 0.5, n - 1 - i + 0.5, cell_text[i][j], ha="center", va="center", fontsize=8)

    # Total column (rightmost, offset by TOTAL_COL_GAP)
    for i, label in enumerate(labels):
        w = int(overall_wins.loc[label])
        l = int(overall_losses.loc[label])
        total = w + l
        if total == 0:
            color = (1.0, 1.0, 1.0, 0.0)
            text = EM_DASH
        else:
            wr_val = w / total
            color = (*cmap(norm(wr_val))[:3], 1.0)
            text = f"{round(100 * wr_val)}% ({w}-{l})"
        ax.add_patch(plt.Rectangle((total_col_left, n - 1 - i), 1, 1, facecolor=color, edgecolor="white"))
        ax.text(total_col_left + 0.5, n - 1 - i + 0.5, text, ha="center", va="center", fontsize=8, weight="bold")

    ax.set_xlim(0, total_col_left + 1)
    ax.set_ylim(0, n)
    ax.set_xticks([j + 0.5 for j in range(n)] + [total_col_left + 0.5])
    ax.set_yticks([n - 1 - i + 0.5 for i in range(n)])
    ax.set_xticklabels(labels + [TOTAL_LABEL], rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Opponent archetype (rightmost: overall total)", fontsize=10)
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


import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matchups", default="data/matchups.csv")
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)

    matchups = pd.read_csv(args.matchups)
    labels = top_n_archetypes(matchups, n=args.top_n) + [OTHER_LABEL]
    long = to_long_frame(matchups, top_n=labels[:-1])  # exclude OTHER from the top-N list
    wins, losses = compute_matrix(long, ordered_labels=labels)
    _assert_symmetric(wins, losses)

    out_dir = Path(args.out_dir)
    render_csvs(wins, losses, out_dir=out_dir)
    render_png(wins, losses, out_path=out_dir / "matchup_matrix.png")

    print(f"Wrote matchup matrix artifacts to {out_dir}:")
    for name in ("matchup_matrix.csv", "matchup_matrix_numeric.csv",
                 "matchup_matrix_counts.csv", "matchup_matrix.png"):
        print(f"  - {name}")


if __name__ == "__main__":
    main()
