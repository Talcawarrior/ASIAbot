#!/usr/bin/env python3
"""
Grid search over min_edge × kelly_fraction for Karpathy weekly.
Uses the existing Karpathy infrastructure with look-ahead bias fix.
"""

import json
import logging
import os
import sys
from itertools import product

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from asi_engine.karpathy_weekly import (
    Hypothesis,
    evaluate_hypothesis_oos,
)
from data_pipeline.unified_datastore import UnifiedDatastore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("KARPATHY_GRID")

# ─── Parameter Grid ────────────────────────────────────────────────────────────
MIN_EDGES = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]
KELLY_FRACTIONS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]
BLEND_WEIGHTS = [0.35, 0.40, 0.45, 0.50]

# Fixed params
MAX_BET_PCT = 0.05
TAIL_FILTER = False


# ─── Load Data Once ────────────────────────────────────────────────────────────
def load_unified_data():
    """Load unified dataset once for all evaluations."""
    logger.info("Loading unified data...")
    ds = UnifiedDatastore()

    # Build brier dataset (uses calibrations + counterfactual + markets)
    brier_df = ds.build_brier_dataset()
    if brier_df is None or brier_df.empty:
        raise ValueError("Brier dataset empty")

    # Add per-model probabilities
    from asi_engine.karpathy_weekly import add_per_model_probabilities

    brier_df = add_per_model_probabilities(brier_df, ds=ds)

    # Build walk-forward splits (reduced params for 12-day data)
    splits = ds.build_walk_forward_splits(lookback_days=7, step_days=2, test_days=2)

    logger.info(f"Loaded {len(brier_df)} rows, {len(splits)} splits")
    return brier_df, splits


def evaluate_params(brier_df, splits, min_edge, kelly_fraction, blend_weight):
    """Evaluate a single parameter combination."""
    hyp = Hypothesis(
        description=f"grid_me{min_edge}_kf{kelly_fraction}_bw{blend_weight}",
        model_weights={
            "gfs_seamless": 0.1111,
            "ecmwf_ifs025": 0.1111,
            "gem_global": 0.1111,
            "icon_global": 0.1111,
            "jma_seamless": 0.1111,
            "cma_grapes_global": 0.1111,
            "ukmo_seamless": 0.1111,
            "meteofrance_seamless": 0.1111,
            "openmeteo": 0.1111,
        },
        min_edge=min_edge,
        kelly_fraction=kelly_fraction,
        max_bet_pct=0.05,
        blend_weight=blend_weight,
        tail_filter_enabled=False,
    )

    per_split = [evaluate_hypothesis_oos(brier_df, s["test_indices"], hyp) for s in splits]

    # Mean stats
    keys = ["sharpe", "roi_pct", "win_rate", "brier_score", "total_pnl", "total_staked", "total_trades"]
    stats = {k: np.mean([s.get(k, 0.0) for s in per_split]) for k in keys}
    stats["total_trades"] = int(np.sum([s.get("total_trades", 0) for s in per_split]))

    return stats


def grid_search():
    """Run grid search over parameter space."""
    brier_df, splits = load_unified_data()

    total = len(MIN_EDGES) * len(KELLY_FRACTIONS) * len(BLEND_WEIGHTS)
    logger.info(
        f"Grid: {len(MIN_EDGES)} min_edge × {len(KELLY_FRACTIONS)} kelly × {len(BLEND_WEIGHTS)} blend = {total} combos"
    )

    results = []
    best_sharpe = -999
    best_combo = None

    for i, (me, kf, bw) in enumerate(product(MIN_EDGES, KELLY_FRACTIONS, BLEND_WEIGHTS)):
        stats = evaluate_params(brier_df, splits, me, kf, bw)
        stats["min_edge"] = me
        stats["kelly_fraction"] = kf
        stats["blend_weight"] = bw
        results.append(stats)

        if stats["sharpe"] > best_sharpe and stats["total_trades"] >= 10:
            best_sharpe = stats["sharpe"]
            best_combo = stats

        if (i + 1) % 20 == 0:
            logger.info(
                f"  [{i + 1}/{len(MIN_EDGES) * len(KELLY_FRACTIONS) * len(BLEND_WEIGHTS)}] best_sharpe={best_sharpe:.4f}"
            )

    return results, best_combo


def print_results(results, top_n=20):
    """Print top results sorted by Sharpe."""
    valid = [r for r in results if r["total_trades"] >= 10]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n{'=' * 100}")
    print(f"TOP {top_n} BY SHARPE (min 10 trades)")
    print(f"{'=' * 100}")
    print(
        f"{'#':>3} {'min_e':>6} {'kelly':>6} {'blend':>6} {'#T':>5} {'W':>4} {'WR%':>6} {'PnL$':>9} {'ROI%':>7} {'Sharpe':>7} {'Brier':>7} {'AvgP':>7}"
    )
    print("-" * 100)
    for i, r in enumerate(valid[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>6.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['total_trades']:>5} {int(r['win_rate'] * r['total_trades']):>4} {r['win_rate'] * 100:>5.1f}% "
            f"${r['total_pnl']:>8.1f} {r['roi_pct']:>6.1f}% {r['sharpe']:>7.4f} {r['brier_score']:>7.4f} ${r['total_pnl'] / max(r['total_trades'], 1):>6.1f}"
        )

    # Also by ROI
    valid.sort(key=lambda r: r["roi_pct"], reverse=True)
    print(f"\n{'=' * 100}")
    print(f"TOP {top_n} BY ROI (min 10 trades)")
    print(f"{'=' * 100}")
    for i, r in enumerate(valid[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>6.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['total_trades']:>5} {int(r['win_rate'] * r['total_trades']):>4} {r['win_rate'] * 100:>5.1f}% "
            f"${r['total_pnl']:>8.1f} {r['roi_pct']:>6.1f}% {r['sharpe']:>7.4f} {r['brier_score']:>7.4f}"
        )


if __name__ == "__main__":
    import numpy as np

    logger.info("Starting Karpathy grid search...")
    results, best = grid_search()
    print_results(results)

    print(f"\n{'=' * 100}")
    print("BEST COMBO (by Sharpe, min 10 trades):")
    print(f"{'=' * 100}")
    for k, v in best.items():
        print(f"  {k}: {v}")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "karpathy_grid_search.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")
