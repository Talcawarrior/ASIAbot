"""
Backtest harness: Replay historical bets with different parameter combinations.

Strategy:
  1. Load all settled bets (won/lost/closed_early) with analysis data
  2. For each parameter combo (min_edge, kelly_fraction, blend_weight):
     a. Re-blend probability: new_prob = blend * est_prob + (1-blend) * implied
     b. Compute edge: |new_prob - implied|
     c. Filter: only bets where edge >= min_edge
     d. Size: kelly fraction of bankroll
     e. PnL: actual PnL scaled by (new_size / actual_size)
  3. Report: ROI, Sharpe, win_rate, total_trades, total_pnl per combo
"""

import json
import math
import os
import sqlite3
import sys
from itertools import product

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.kelly import kelly_fraction as kf

DB_PATH = os.path.join(PROJECT_ROOT, "data", "bot.db")
INITIAL_BANKROLL = 1000.0
WEATHER_FEE_RATE = 0.05


def load_settled_bets():
    """Load all settled bets with analysis data."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT b.id, b.side, b.entry_price, b.shares, b.amount, b.pnl, b.status,
               b.close_reason, b.city, b.outcome,
               a.estimated_probability, a.edge, a.raw_edge, a.market_implied_prob,
               a.model_predictions, a.confidence_score
        FROM bets b
        JOIN analyses a ON b.analysis_id = a.id
        WHERE b.status IN ('won', 'lost', 'closed_early')
        AND b.entry_price IS NOT NULL AND b.entry_price > 0
        AND b.entry_price < 1.0
        AND a.estimated_probability IS NOT NULL
        AND a.market_implied_prob IS NOT NULL
        AND a.market_implied_prob > 0 AND a.market_implied_prob < 1.0
        ORDER BY b.id
    """)
    bets = [dict(row) for row in c.fetchall()]
    conn.close()
    return bets


def reevaluate_bet(bet, blend_weight, min_edge, kelly_fraction, bankroll):
    """Re-evaluate a single bet with new parameters.

    Returns (would_bet, scaled_pnl) or (False, 0) if filtered out.
    """
    est_prob = bet["estimated_probability"]
    implied = bet["market_implied_prob"]
    side = bet["side"]
    entry = bet["entry_price"]
    actual_pnl = bet["pnl"] or 0
    actual_amount = bet["amount"] or 1.0

    # 1. Re-blend probability
    new_prob = blend_weight * est_prob + (1 - blend_weight) * implied
    new_prob = max(0.01, min(0.99, new_prob))

    # 2. Compute edge
    if side == "YES":
        prob_for_kelly = new_prob
        entry_for_kelly = entry
    else:  # NO
        prob_for_kelly = 1.0 - new_prob
        entry_for_kelly = 1.0 - entry

    if entry_for_kelly <= 0 or entry_for_kelly >= 1:
        return False, 0.0

    edge = prob_for_kelly - entry_for_kelly

    # 3. Filter by min_edge
    if abs(edge) < min_edge:
        return False, 0.0

    # 4. Kelly sizing
    f_star = kf(prob_for_kelly, entry_for_kelly)
    if f_star <= 0:
        return False, 0.0

    new_amount = bankroll * min(f_star * kelly_fraction, 0.006)
    if new_amount < 1.0:
        return False, 0.0

    # 5. Scale PnL
    scale = new_amount / actual_amount if actual_amount > 0 else 0
    scaled_pnl = actual_pnl * scale

    return True, scaled_pnl


def run_backtest(bets, blend_weight, min_edge, kelly_fraction, bankroll=INITIAL_BANKROLL):
    """Run backtest for one parameter combination."""
    pnls = []
    total_staked = 0.0

    for bet in bets:
        would_bet, scaled_pnl = reevaluate_bet(bet, blend_weight, min_edge, kelly_fraction, bankroll)
        if would_bet:
            pnls.append(scaled_pnl)
            # Estimate stake from the bet amount ratio
            actual_amount = bet["amount"] or 1.0
            new_amount = bankroll * min(
                kf(
                    bet["estimated_probability"] if bet["side"] == "YES" else 1 - bet["estimated_probability"],
                    bet["entry_price"] if bet["side"] == "YES" else 1 - bet["entry_price"],
                )
                * kelly_fraction,
                0.006,
            )
            total_staked += new_amount

    if not pnls:
        return {
            "trades": 0,
            "wins": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "roi_pct": 0,
            "sharpe": 0,
            "avg_pnl": 0,
            "max_drawdown": 0,
            "total_staked": 0,
        }

    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    mean_pnl = total_pnl / len(pnls)
    var_pnl = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
    std_pnl = math.sqrt(var_pnl) if var_pnl > 0 else 1e-5
    sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0

    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    roi_pct = (total_pnl / total_staked * 100) if total_staked > 0 else 0

    return {
        "trades": len(pnls),
        "wins": wins,
        "win_rate": round(wins / len(pnls), 4),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi_pct, 2),
        "sharpe": round(sharpe, 4),
        "avg_pnl": round(mean_pnl, 4),
        "max_drawdown": round(max_dd, 2),
        "total_staked": round(total_staked, 2),
    }


def grid_search(bets):
    """Grid search over parameter space."""
    # Parameter ranges
    min_edges = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]
    kelly_fractions = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]
    blend_weights = [0.35, 0.40, 0.45, 0.50]

    total = len(min_edges) * len(kelly_fractions) * len(blend_weights)
    print(
        f"Grid search: {len(min_edges)} min_edge x {len(kelly_fractions)} kelly x {len(blend_weights)} blend = {total} combinations"
    )
    print(f"Loaded {len(bets)} settled bets with analysis data\n")

    results = []
    best_sharpe = -999
    best_combo = None
    best_idx = 0

    for i, (me, kf_val, bw) in enumerate(product(min_edges, kelly_fractions, blend_weights)):
        stats = run_backtest(bets, bw, me, kf_val)
        stats["min_edge"] = me
        stats["kelly_fraction"] = kf_val
        stats["blend_weight"] = bw
        results.append(stats)

        # Track best by Sharpe (primary) then ROI (secondary)
        if stats["sharpe"] > best_sharpe and stats["trades"] >= 10:
            best_sharpe = stats["sharpe"]
            best_combo = stats
            best_idx = i

        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{total}] best_sharpe={best_sharpe:.4f}")

    return results, best_combo


def print_top_results(results, top_n=20):
    """Print top N results sorted by Sharpe."""
    # Filter for minimum trades
    valid = [r for r in results if r["trades"] >= 10]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n{'=' * 100}")
    print(f"TOP {top_n} RESULTS BY SHARPE (min 10 trades)")
    print(f"{'=' * 100}")
    print(
        f"{'#':>3} {'min_edge':>8} {'kelly':>6} {'blend':>6} {'trades':>7} {'wins':>5} {'win%':>6} {'PnL':>10} {'ROI%':>8} {'Sharpe':>8} {'AvgPnL':>8} {'MaxDD':>8}"
    )
    print("-" * 100)
    for i, r in enumerate(valid[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>8.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['trades']:>7} {r['wins']:>5} {r['win_rate'] * 100:>5.1f}% "
            f"${r['total_pnl']:>9.2f} {r['roi_pct']:>7.1f}% {r['sharpe']:>8.4f} "
            f"${r['avg_pnl']:>7.2f} ${r['max_drawdown']:>7.2f}"
        )

    # Also sort by ROI
    valid_by_roi = sorted(valid, key=lambda r: r["roi_pct"], reverse=True)
    print(f"\n{'=' * 100}")
    print(f"TOP {top_n} RESULTS BY ROI (min 10 trades)")
    print(f"{'=' * 100}")
    print(
        f"{'#':>3} {'min_edge':>8} {'kelly':>6} {'blend':>6} {'trades':>7} {'wins':>5} {'win%':>6} {'PnL':>10} {'ROI%':>8} {'Sharpe':>8} {'AvgPnL':>8} {'MaxDD':>8}"
    )
    print("-" * 100)
    for i, r in enumerate(valid_by_roi[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>8.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['trades']:>7} {r['wins']:>5} {r['win_rate'] * 100:>5.1f}% "
            f"${r['total_pnl']:>9.2f} {r['roi_pct']:>7.1f}% {r['sharpe']:>8.4f} "
            f"${r['avg_pnl']:>7.2f} ${r['max_drawdown']:>7.2f}"
        )

    # Balanced: Sharpe * sqrt(trades) — reward both performance and volume
    for r in valid:
        r["balanced_score"] = (
            r["sharpe"] * math.sqrt(r["trades"]) if r["sharpe"] > 0 else r["sharpe"] * math.sqrt(r["trades"])
        )
    valid_by_balanced = sorted(valid, key=lambda r: r["balanced_score"], reverse=True)
    print(f"\n{'=' * 100}")
    print(f"TOP {top_n} RESULTS BY BALANCED SCORE (Sharpe * sqrt(trades))")
    print(f"{'=' * 100}")
    print(
        f"{'#':>3} {'min_edge':>8} {'kelly':>6} {'blend':>6} {'trades':>7} {'wins':>5} {'win%':>6} {'PnL':>10} {'ROI%':>8} {'Sharpe':>8} {'BalScore':>9}"
    )
    print("-" * 100)
    for i, r in enumerate(valid_by_balanced[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>8.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['trades']:>7} {r['wins']:>5} {r['win_rate'] * 100:>5.1f}% "
            f"${r['total_pnl']:>9.2f} {r['roi_pct']:>7.1f}% {r['sharpe']:>8.4f} "
            f"{r['balanced_score']:>9.4f}"
        )


if __name__ == "__main__":
    print("Loading settled bets...")
    bets = load_settled_bets()
    print(f"Loaded {len(bets)} bets\n")

    results, best = grid_search(bets)
    print_top_results(results)

    print(f"\n{'=' * 100}")
    print("BEST COMBO (by Sharpe, min 10 trades):")
    print(f"{'=' * 100}")
    for k, v in best.items():
        if k != "balanced_score":
            print(f"  {k}: {v}")

    # Save results
    out_path = os.path.join(PROJECT_ROOT, "data", "backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")
