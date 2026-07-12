"""
Backtest v2: Accurate replay using natural bet outcomes.

Key fix from v1: Don't scale PnL by bet size ratio. Instead:
  - Won bets: payout = stake / entry_price * (1 - fee), net = payout - stake - fee
  - Lost bets: net = -stake - fee
  - Closed_early: use actual PnL as-is (exit logic is complex)

This gives accurate results because won/lost outcomes are binary and
deterministic from entry_price alone.
"""

import json
import math
import os
import sqlite3
import sys
from itertools import product

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from utils.kelly import kelly_fraction as kf  # noqa: E402
from utils.formulas import polymarket_fee, bet_shares  # noqa: E402

DB_PATH = os.path.join(PROJECT_ROOT, "data", "bot.db")
INITIAL_BANKROLL = 1000.0
WEATHER_FEE_RATE = 0.05
MAX_BET_PCT = 0.006  # matches config/settings.py


def load_settled_bets():
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


def simulate_trade(bet, blend_weight, min_edge, kelly_fraction, bankroll):
    """
    Simulate one trade with new parameters.

    Returns (would_bet, pnl) or (False, 0) if filtered out.
    """
    est_prob = bet["estimated_probability"]
    implied = bet["market_implied_prob"]
    side = bet["side"]
    entry = bet["entry_price"]
    status = bet["status"]
    actual_pnl = bet["pnl"] or 0

    # 1. Re-blend probability
    new_prob = blend_weight * est_prob + (1 - blend_weight) * implied
    new_prob = max(0.01, min(0.99, new_prob))

    # 2. Determine bet side and compute edge
    if side == "YES":
        prob_for_kelly = new_prob
        entry_for_kelly = entry
    else:  # NO
        prob_for_kelly = 1.0 - new_prob
        entry_for_kelly = 1.0 - entry

    if entry_for_kelly <= 0 or entry_for_kelly >= 1 or prob_for_kelly <= 0 or prob_for_kelly >= 1:
        return False, 0.0

    edge = prob_for_kelly - entry_for_kelly

    # 3. Filter by min_edge
    if abs(edge) < min_edge:
        return False, 0.0

    # 4. Kelly sizing
    f_star = kf(prob_for_kelly, entry_for_kelly)
    if f_star <= 0:
        return False, 0.0

    stake = bankroll * min(f_star * kelly_fraction, MAX_BET_PCT)
    if stake < 1.0:
        return False, 0.0

    # 5. Compute PnL based on actual outcome
    if status == "won":
        # Won: payout = stake / entry, minus fee
        shares = bet_shares(stake, entry)
        payout = shares  # each share pays $1 on win
        fee = polymarket_fee(shares, entry, WEATHER_FEE_RATE)
        pnl = payout - stake - fee
    elif status == "lost":
        # Lost: lose stake + fee
        shares = bet_shares(stake, entry)
        fee = polymarket_fee(shares, entry, WEATHER_FEE_RATE)
        pnl = -(stake + fee)
    elif status == "closed_early":
        # For closed_early, scale the actual PnL by bet size ratio
        actual_amount = bet["amount"] or 1.0
        scale = stake / actual_amount if actual_amount > 0 else 0
        pnl = actual_pnl * scale
    else:
        return False, 0.0

    return True, pnl


def run_backtest(bets, blend_weight, min_edge, kelly_fraction, bankroll=INITIAL_BANKROLL):
    pnls = []
    total_staked = 0.0

    for bet in bets:
        would_bet, pnl = simulate_trade(bet, blend_weight, min_edge, kelly_fraction, bankroll)
        if would_bet:
            pnls.append(pnl)
            # Estimate stake
            est_prob = bet["estimated_probability"]
            implied = bet["market_implied_prob"]
            side = bet["side"]
            entry = bet["entry_price"]
            new_prob = blend_weight * est_prob + (1 - blend_weight) * implied
            if side == "YES":
                pk, ek = new_prob, entry
            else:
                pk, ek = 1.0 - new_prob, 1.0 - entry
            if 0 < ek < 1 and 0 < pk < 1:
                f = kf(pk, ek)
                if f > 0:
                    stake = bankroll * min(f * kelly_fraction, MAX_BET_PCT)
                    total_staked += stake

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
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
        }

    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    mean_pnl = total_pnl / len(pnls)
    var_pnl = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
    std_pnl = math.sqrt(var_pnl) if var_pnl > 0 else 1e-5
    sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    roi_pct = (total_pnl / total_staked * 100) if total_staked > 0 else 0

    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    gross_wins = sum(win_pnls)
    gross_losses = abs(sum(loss_pnls))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 999

    return {
        "trades": len(pnls),
        "wins": wins,
        "losses": len(pnls) - wins,
        "win_rate": round(wins / len(pnls), 4),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi_pct, 2),
        "sharpe": round(sharpe, 4),
        "avg_pnl": round(mean_pnl, 4),
        "max_drawdown": round(max_dd, 2),
        "total_staked": round(total_staked, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
    }


def grid_search(bets):
    min_edges = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]
    kelly_fractions = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]
    blend_weights = [0.35, 0.40, 0.45, 0.50]

    total = len(min_edges) * len(kelly_fractions) * len(blend_weights)
    print(f"Grid: {len(min_edges)} x {len(kelly_fractions)} x {len(blend_weights)} = {total} combos")
    print(f"Bets: {len(bets)} settled\n")

    results = []
    best_score = -999
    best = None

    for i, (me, kf_val, bw) in enumerate(product(min_edges, kelly_fractions, blend_weights)):
        stats = run_backtest(bets, bw, me, kf_val)
        stats["min_edge"] = me
        stats["kelly_fraction"] = kf_val
        stats["blend_weight"] = bw
        results.append(stats)

        # Best = highest Sharpe with >= 10 trades
        score = stats["sharpe"]
        if score > best_score and stats["trades"] >= 10:
            best_score = score
            best = stats

        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{total}] best_sharpe={best_score:.4f}")

    return results, best


def print_results(results, top_n=25):
    valid = [r for r in results if r["trades"] >= 10]

    # By Sharpe
    by_sharpe = sorted(valid, key=lambda r: r["sharpe"], reverse=True)
    print(f"\n{'=' * 120}")
    print(f"TOP {top_n} BY SHARPE (min 10 trades)")
    print(f"{'=' * 120}")
    hdr = (
        f"{'#':>3} {'min_e':>6} {'kelly':>6} {'blend':>6} {'#T':>5} "
        f"{'W':>4} {'WR%':>6} {'PnL$':>9} {'ROI%':>7} {'Sharpe':>7} "
        f"{'AvgP':>7} {'AvgW':>7} {'AvgL':>7} {'PF':>5} {'MaxDD':>7}"
    )
    print(hdr)
    print("-" * 120)
    for i, r in enumerate(by_sharpe[:top_n]):
        row = (
            f"{i + 1:>3} {r['min_edge']:>6.2f} {r['kelly_fraction']:>6.2f} "
            f"{r['blend_weight']:>6.2f} {r['trades']:>5} {r['wins']:>4} "
            f"{r['win_rate'] * 100:>5.1f}% {r['total_pnl']:>8.1f} "
            f"{r['roi_pct']:>6.1f}% {r['sharpe']:>7.4f} {r['avg_pnl']:>6.2f} "
            f"{r['avg_win']:>6.2f} {r['avg_loss']:>6.2f} "
            f"{r['profit_factor']:>5.1f} {r['max_drawdown']:>6.1f}"
        )
        print(row)

    # By ROI
    by_roi = sorted(valid, key=lambda r: r["roi_pct"], reverse=True)
    print(f"\n{'=' * 120}")
    print(f"TOP {top_n} BY ROI (min 10 trades)")
    print(f"{'=' * 120}")
    print(hdr)
    print("-" * 120)
    for i, r in enumerate(by_roi[:top_n]):
        row = (
            f"{i + 1:>3} {r['min_edge']:>6.2f} {r['kelly_fraction']:>6.2f} "
            f"{r['blend_weight']:>6.2f} {r['trades']:>5} {r['wins']:>4} "
            f"{r['win_rate'] * 100:>5.1f}% {r['total_pnl']:>8.1f} "
            f"{r['roi_pct']:>6.1f}% {r['sharpe']:>7.4f} {r['avg_pnl']:>6.2f} "
            f"{r['avg_win']:>6.2f} {r['avg_loss']:>6.2f} "
            f"{r['profit_factor']:>5.1f} {r['max_drawdown']:>6.1f}"
        )
        print(row)

    # Balanced: Sharpe * sqrt(trades)
    for r in valid:
        r["balanced"] = r["sharpe"] * math.sqrt(r["trades"])
    by_bal = sorted(valid, key=lambda r: r["balanced"], reverse=True)
    print(f"\n{'=' * 120}")
    print(f"TOP {top_n} BY BALANCED (Sharpe * sqrt(trades))")
    print(f"{'=' * 120}")
    hdr_bal = (
        f"{'#':>3} {'min_e':>6} {'kelly':>6} {'blend':>6} {'#T':>5} "
        f"{'W':>4} {'WR%':>6} {'PnL$':>9} {'ROI%':>7} {'Sharpe':>7} {'Bal':>7}"
    )
    print(hdr_bal)
    print("-" * 120)
    for i, r in enumerate(by_bal[:top_n]):
        print(
            f"{i + 1:>3} {r['min_edge']:>6.2f} {r['kelly_fraction']:>6.2f} {r['blend_weight']:>6.2f} "
            f"{r['trades']:>5} {r['wins']:>4} {r['win_rate'] * 100:>5.1f}% "
            f"{r['total_pnl']:>8.1f} {r['roi_pct']:>6.1f}% {r['sharpe']:>7.4f} "
            f"{r['balanced']:>7.4f}"
        )

    # Current config shown in main block


if __name__ == "__main__":
    print("Loading bets...")
    bets = load_settled_bets()
    print(f"Loaded {len(bets)}\n")

    results, best = grid_search(bets)
    print_results(results)

    # Best
    print(f"\n{'=' * 120}")
    print("BEST (by Sharpe, min 10 trades):")
    print(f"{'=' * 120}")
    for k, v in best.items():
        if k not in ("balanced",):
            print(f"  {k}: {v}")

    # Current config comparison
    print(f"\n{'=' * 120}")
    print("CURRENT CONFIG (min_edge=0.05, kelly=0.15, blend=0.45):")
    print(f"{'=' * 120}")
    current = run_backtest(bets, 0.45, 0.05, 0.15)
    for k, v in current.items():
        print(f"  {k}: {v}")

    # Save
    out = os.path.join(PROJECT_ROOT, "data", "backtest_results_v2.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {out}")
