"""Diagnose the asymmetric payoff problem.

Win rate is ~91% but ROI is negative — that means the bot wins many small
bets and loses a few large ones. This script breaks down the trade
distribution to confirm where the bleed is coming from.
"""

import math
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Make the ASIAbot repo importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from asi_engine.cognition_base import CognitionBase  # noqa: E402
from database.db import DB_PATH  # noqa: E402
from utils.kelly import kelly_bet_amount  # noqa: E402
from utils.probability import estimate_probability  # noqa: E402


def diagnose(parameters: dict) -> dict:
    model_weights = parameters["model_weights"]
    min_edge = parameters["min_edge"]
    kelly_fraction = parameters["kelly_fraction"]

    rng = random.Random(42)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT city_code, city, date, metric, actual_value
        FROM historical_calibrations
        GROUP BY city_code, date, metric
        ORDER BY date ASC
        """
    )
    groups = cursor.fetchall()

    strike_grid = [round(0.5 * k, 1) for k in range(-20, 80)]

    trades = []
    brier_errors = []
    bankroll = 10000.0

    for city_code, city_name, date_str, metric, actual_val in groups:
        cursor.execute(
            """
            SELECT model, predicted_value
            FROM historical_calibrations
            WHERE city_code = ? AND date = ? AND metric = ?
            """,
            (city_code, date_str, metric),
        )
        preds = dict(cursor.fetchall())
        if not preds:
            continue

        weight_sum = sum(model_weights.get(m, 0.0) for m in preds)
        if weight_sum <= 0:
            continue

        weighted_temp = (
            sum(model_weights.get(m, 0.0) * val for m, val in preds.items())
            / weight_sum
        )
        strike = rng.choice(strike_grid)
        outcome_yes = actual_val > strike

        pred_vals = list(preds.values())
        mean = sum(pred_vals) / len(pred_vals)
        std = (
            max(
                (sum((x - mean) ** 2 for x in pred_vals) / (len(pred_vals) - 1)) ** 0.5,
                1.0,
            )
            if len(pred_vals) > 1
            else 1.5
        )

        prob = estimate_probability(
            mean=weighted_temp,
            std=std,
            threshold=strike,
            days_ahead=2,
            market_type="HIGH",
        )
        brier_errors.append((prob - (1.0 if outcome_yes else 0.0)) ** 2)

        naive_z = (strike - mean) / max(std, 1.0)
        naive_p_yes = 0.5 * (1.0 + math.erf(-naive_z / math.sqrt(2.0)))
        inefficiency = rng.gauss(0.0, 0.07)
        raw_price = naive_p_yes + inefficiency
        raw_price = 0.5 + (raw_price - 0.5) * 0.98
        yes_price = max(0.05, min(0.95, raw_price))
        no_price = 1.0 - yes_price

        yes_edge = prob - yes_price
        no_edge = (1.0 - prob) - no_price

        if yes_edge > no_edge:
            sim_side = "YES"
            sim_edge = yes_edge
            entry_price = yes_price
        else:
            sim_side = "NO"
            sim_edge = no_edge
            entry_price = no_price

        ev = sim_edge - 0.02
        if sim_edge >= min_edge and ev > 0:
            prob_win = prob if sim_side == "YES" else (1.0 - prob)
            bet_size = kelly_bet_amount(
                bankroll,
                prob_win,
                entry_price,
                fraction=kelly_fraction,
                min_bet=1.0,
                max_bet_pct=0.03,
            )

            won = (sim_side == "YES" and outcome_yes) or (
                sim_side == "NO" and not outcome_yes
            )

            if won:
                payout = bet_size / entry_price
                fee = payout * 0.02
                pnl = payout - bet_size - fee
            else:
                pnl = -bet_size

            trades.append(
                {
                    "side": sim_side,
                    "entry_price": entry_price,
                    "edge": sim_edge,
                    "bet_size": bet_size,
                    "pnl": pnl,
                    "won": won,
                    "prob_win": prob_win,
                }
            )
            bankroll += pnl

    conn.close()

    if not trades:
        return {"trades": 0}

    pnls = [t["pnl"] for t in trades]
    wins = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]

    total_staked = sum(t["bet_size"] for t in trades)
    net_pnl = sum(pnls)
    roi_pct = (net_pnl / total_staked * 100.0) if total_staked > 0 else 0.0

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
    avg_win_size = sum(t["bet_size"] for t in wins) / len(wins) if wins else 0.0
    avg_loss_size = sum(t["bet_size"] for t in losses) / len(losses) if losses else 0.0

    buckets = defaultdict(lambda: {"n": 0, "won": 0, "pnl": 0.0, "stake": 0.0})
    for t in trades:
        bucket = round(t["entry_price"] * 10) / 10
        buckets[bucket]["n"] += 1
        buckets[bucket]["won"] += 1 if t["won"] else 0
        buckets[bucket]["pnl"] += t["pnl"]
        buckets[bucket]["stake"] += t["bet_size"]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades),
        "net_pnl": net_pnl,
        "total_staked": total_staked,
        "roi_pct": roi_pct,
        "avg_win_pnl": avg_win,
        "avg_loss_pnl": avg_loss,
        "avg_win_size": avg_win_size,
        "avg_loss_size": avg_loss_size,
        "loss_to_win_pnl_ratio": (
            abs(avg_loss / avg_win) if avg_win != 0 else float("inf")
        ),
        "brier": sum(brier_errors) / len(brier_errors) if brier_errors else 0.25,
        "buckets": dict(buckets),
    }


if __name__ == "__main__":
    cb = CognitionBase()
    params = cb.get_best_parameters()
    print("=== Current parameters ===")
    print(f"  min_edge: {params['min_edge']}")
    print(f"  kelly_fraction: {params['kelly_fraction']}")
    print()

    result = diagnose(params)
    print("=== Diagnostic Results ===")
    print(f"  Total trades:  {result['trades']}")
    print(f"  Wins/Losses:   {result['wins']}/{result['losses']}")
    print(f"  Win rate:      {result['win_rate']:.4f}")
    print(f"  Net PnL:       ${result['net_pnl']:.2f}")
    print(f"  Total staked:  ${result['total_staked']:.2f}")
    print(f"  ROI %:         {result['roi_pct']:.2f}%")
    print(f"  Brier score:   {result['brier']:.4f}")
    print()
    print("=== Asymmetric payoff breakdown ===")
    print(
        f"  Avg win  PnL: +${result['avg_win_pnl']:.2f} (avg stake ${result['avg_win_size']:.2f})"
    )
    print(
        f"  Avg loss PnL: ${result['avg_loss_pnl']:.2f} (avg stake ${result['avg_loss_size']:.2f})"
    )
    print(f"  Loss/Win PnL ratio: {result['loss_to_win_pnl_ratio']:.2f}x")
    print()
    print("=== PnL by market price bucket ===")
    print(
        f"  {'Price':>6}  {'N':>4}  {'WinR':>5}  {'PnL':>10}  {'Stake':>10}  {'ROI%':>6}"
    )
    for bucket in sorted(result["buckets"].keys()):
        b = result["buckets"][bucket]
        roi = (b["pnl"] / b["stake"] * 100) if b["stake"] > 0 else 0
        print(
            f"  {bucket:>6.1f}  {b['n']:>4}  {b['won'] / b['n']:>5.2f}  ${b['pnl']:>9.2f}  ${b['stake']:>9.2f}  {roi:>6.1f}"
        )
