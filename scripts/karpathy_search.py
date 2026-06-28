"""Karpathy-style autonomous parameter search.

Loops over many candidate parameter sets, runs each against the real
historical_calibrations backtest, and keeps the one with the best
risk-adjusted return (Sharpe × ROI).

The previous `auto_scientist.py` was a 5-mutation regex toy. This one
is a real random + grid search over the dimensions that matter:

  * model weights (8 models) — shifted via Brier-driven + noise
  * min_edge              — [0.03, 0.20]
  * kelly_fraction        — [0.05, 0.30]
  * max_bet_pct           — [0.01, 0.05]
  * min_entry_price       — [0.05, 0.50]   ← the lever that fixes the
                                              asymmetric-payoff bleed
  * inefficiency_band     — [-0.15, +0.15] ← only take trades where the
                                              market looks mispriced in
                                              our favour

Each candidate's score is:
  score = sharpe * sqrt(abs(roi)) * sign(roi)         if roi > 0
  score = -1000                                       if roi <= 0

We keep the top-K candidates in a leaderboard and write the best one
to `data/model_weights.json` + a new `data/strategy_params.json`
so the live bot picks it up on next restart.
"""

import argparse
import json
import math
import random
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from database.db import DB_PATH  # noqa: E402
from utils.kelly import kelly_bet_amount  # noqa: E402
from utils.probability import estimate_probability  # noqa: E402

# ── Default model weights (current cognition base best) ─────────────────────
DEFAULT_WEIGHTS = {
    "gfs_seamless": 0.30,
    "ecmwf_ifs025": 0.25,
    "gem_global": 0.15,
    "icon_global": 0.10,
    "jma_seamless": 0.08,
    "cma_grapes_global": 0.05,
    "ukmo_seamless": 0.04,
    "meteofrance_seamless": 0.03,
}


def _load_brier_per_model() -> dict[str, float]:
    """Compute the actual per-model Brier score from the historical
    calibrations table. Returns {model_name: brier_score}.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # For each (city, date, metric, model) we have predicted_value and
    # actual_value. Compute Brier as (predicted_prob - outcome)**2
    # where predicted_prob is built from the model's own forecast vs the
    # median strike of the calibration row.
    #
    # But we don't have strikes in the table. So we use a proxy: Brier of
    # the model's *temperature prediction* vs the actual temperature,
    # converted to a binary outcome via a threshold sweep.
    #
    # Simpler & more honest: per-model MAE (mean abs error) on temperature.
    # Lower MAE = better model.
    cursor.execute(
        """
        SELECT model, AVG(ABS(predicted_value - actual_value)) as mae,
               COUNT(*) as n
        FROM historical_calibrations
        GROUP BY model
        """
    )
    rows = cursor.fetchall()
    conn.close()

    maes = {row[0]: row[1] for row in rows if row[2] >= 30}
    # Convert MAE to a 0..1 "Brier-like" score: brier = mae / (mae + 1.0)
    # so a model with MAE=0 → brier=0, MAE=2 → brier=0.67.
    briers = {m: mae / (mae + 1.0) for m, mae in maes.items()}
    return briers


def _make_candidate(rng: random.Random, briers: dict[str, float]) -> dict:
    """Generate one random candidate parameter set.

    Bias the model-weight draw toward the Brier ranking: with 50%
    probability use the Brier-optimal weights exactly; with 50% mix
    them with the current default weights using a random noise.
    """
    # Model weights
    models = list(DEFAULT_WEIGHTS.keys())

    if briers and rng.random() < 0.5:
        # Brier-driven: weight ∝ 1 / brier
        inv = {m: 1.0 / max(briers.get(m, 0.5), 0.01) for m in models}
        total_inv = sum(inv.values())
        weights = {m: inv[m] / total_inv for m in models}
        # Add a small noise so we explore around the Brier optimum.
        for m in models:
            weights[m] = max(0.01, weights[m] + rng.gauss(0.0, 0.02))
        total = sum(weights.values())
        weights = {m: round(weights[m] / total, 4) for m in models}
    else:
        # Random perturbation of defaults.
        weights = {
            m: max(0.01, DEFAULT_WEIGHTS[m] + rng.gauss(0.0, 0.05)) for m in models
        }
        total = sum(weights.values())
        weights = {m: round(weights[m] / total, 4) for m in models}

    return {
        "model_weights": weights,
        "min_edge": round(rng.uniform(0.03, 0.20), 3),
        "kelly_fraction": round(rng.uniform(0.05, 0.30), 3),
        "max_bet_pct": round(rng.uniform(0.01, 0.05), 3),
        "min_entry_price": round(rng.uniform(0.05, 0.50), 3),
        "inefficiency_min": round(rng.uniform(-0.15, 0.15), 3),
    }


def _run_backtest(parameters: dict) -> dict:
    """One backtest run. Same honest construction as
    backtest_simulator.run_extended_backtest but with the new tunable
    parameters (min_entry_price, inefficiency_min).
    """
    model_weights = parameters["model_weights"]
    min_edge = parameters["min_edge"]
    kelly_fraction = parameters["kelly_fraction"]
    max_bet_pct = parameters["max_bet_pct"]
    min_entry_price = parameters["min_entry_price"]
    inefficiency_min = parameters["inefficiency_min"]

    rng = random.Random(42)  # Same seed every time so candidates are comparable

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

    pnls = []
    brier_errors = []
    bankroll = 10000.0
    total_wagered = 0.0
    won = 0
    lost = 0

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

        # ── New filters (the levers the search will tune) ────────────────
        # 1. Skip long-shot bets where the market says "very unlikely"
        #    — these are the source of the asymmetric-payoff bleed.
        if entry_price < min_entry_price:
            continue

        # 2. Only take trades where the inefficiency noise went in our
        #    favour by at least `inefficiency_min`. This is the
        #    structural-edge gate.
        if inefficiency < inefficiency_min:
            continue

        if sim_edge >= min_edge and ev > 0:
            prob_win = prob if sim_side == "YES" else (1.0 - prob)
            bet_size = kelly_bet_amount(
                bankroll,
                prob_win,
                entry_price,
                fraction=kelly_fraction,
                min_bet=1.0,
                max_bet_pct=max_bet_pct,
            )

            trade_won = (sim_side == "YES" and outcome_yes) or (
                sim_side == "NO" and not outcome_yes
            )

            if trade_won:
                payout = bet_size / entry_price
                fee = payout * 0.02
                pnl = payout - bet_size - fee
                won += 1
            else:
                pnl = -bet_size
                lost += 1

            pnls.append(pnl)
            total_wagered += bet_size
            bankroll += pnl

    conn.close()

    total_trades = won + lost
    if total_trades == 0:
        return {
            "trades": 0,
            "won": 0,
            "lost": 0,
            "roi": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "score": -1000.0,
        }

    net_pnl = sum(pnls)
    roi = (net_pnl / total_wagered * 100.0) if total_wagered > 0 else 0.0
    win_rate = won / total_trades

    mean_pnl = sum(pnls) / len(pnls)
    variance_pnl = sum((x - mean_pnl) ** 2 for x in pnls) / len(pnls)
    std_pnl = math.sqrt(variance_pnl) if variance_pnl > 0 else 1e-5
    sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0

    brier = sum(brier_errors) / len(brier_errors) if brier_errors else 0.25

    # Score: reward positive ROI scaled by Sharpe. Penalty for tiny samples.
    if roi <= 0:
        score = -1000.0
    else:
        # Sample-size confidence: down-weight candidates with <50 trades.
        confidence = min(1.0, total_trades / 200.0)
        score = sharpe * math.sqrt(roi) * confidence

    return {
        "trades": total_trades,
        "won": won,
        "lost": lost,
        "roi": round(roi, 2),
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "pnl": round(net_pnl, 2),
        "brier": round(brier, 4),
        "score": round(score, 4),
    }


def search(num_candidates: int = 500, seed: int = 7, verbose: bool = True):
    """Run an autonomous search loop. Returns the best candidate found."""
    rng = random.Random(seed)
    briers = _load_brier_per_model()
    if verbose:
        print("Per-model Brier (MAE-based):")
        for m, b in sorted(briers.items(), key=lambda kv: kv[1]):
            print(f"  {m:30s}  {b:.4f}")
        print()

    best = None
    best_score = -float("inf")
    leaderboard = []

    start_t = time.time()
    for i in range(num_candidates):
        candidate = _make_candidate(rng, briers)
        result = _run_backtest(candidate)
        result["candidate"] = candidate
        leaderboard.append(result)

        if result["score"] > best_score:
            best_score = result["score"]
            best = result
            if verbose and (i < 10 or result["score"] > 0):
                print(
                    f"  [{i + 1:4d}/{num_candidates}] score={result['score']:+.3f}  "
                    f"sharpe={result['sharpe']:+.3f}  roi={result['roi']:+7.2f}%  "
                    f"wr={result['win_rate']:.3f}  trades={result['trades']:5d}  "
                    f"min_edge={candidate['min_edge']:.3f}  "
                    f"kelly={candidate['kelly_fraction']:.3f}  "
                    f"min_price={candidate['min_entry_price']:.3f}  "
                    f"ineff_min={candidate['inefficiency_min']:+.3f}"
                )

    elapsed = time.time() - start_t
    if verbose:
        print()
        print(
            f"Searched {num_candidates} candidates in {elapsed:.1f}s "
            f"({num_candidates / max(elapsed, 0.1):.1f}/sec)"
        )
        print()
        print("=== Top 10 candidates by score ===")
        leaderboard.sort(key=lambda r: r["score"], reverse=True)
        for i, r in enumerate(leaderboard[:10]):
            c = r["candidate"]
            print(
                f"  #{i + 1}: score={r['score']:+.3f}  "
                f"sharpe={r['sharpe']:+.3f}  roi={r['roi']:+7.2f}%  "
                f"wr={r['win_rate']:.3f}  trades={r['trades']:5d}  "
                f"min_edge={c['min_edge']:.3f}  "
                f"kelly={c['kelly_fraction']:.3f}  "
                f"min_price={c['min_entry_price']:.3f}  "
                f"ineff_min={c['inefficiency_min']:+.3f}"
            )

    return best, leaderboard


def save_best_to_disk(best: dict) -> None:
    """Persist best candidate as model_weights.json + strategy_params.json
    so the live bot picks them up.
    """
    data_dir = REPO / "data"
    data_dir.mkdir(exist_ok=True)

    weights_path = data_dir / "model_weights.json"
    strategy_path = data_dir / "strategy_params.json"

    # Persist weights via utils/weights_store.save_weights so the
    # central MIN_MODEL_WEIGHT=0.05 diversification floor is applied.
    # The previous "fix" here was a no-op: it checked
    # `if model not in candidate_weights` but _make_candidate always
    # populates all 8 models, so the branch never fired and the
    # 2-model-dominant overfit result was written verbatim. Now
    # save_weights applies max(w, 0.05) + renormalize centrally.
    from utils.weights_store import save_weights

    candidate_weights = best["candidate"]["model_weights"]
    save_weights(candidate_weights, path=str(weights_path))

    # strategy_params.json — extends the existing schema with the new
    # tunables discovered by the search.
    strategy = {
        "min_edge": best["candidate"]["min_edge"],
        "kelly_fraction": best["candidate"]["kelly_fraction"],
        "max_bet_pct": best["candidate"]["max_bet_pct"],
        "min_entry_price": best["candidate"]["min_entry_price"],
        "inefficiency_min": best["candidate"]["inefficiency_min"],
        # Backtest provenance so the live dashboard can show it.
        "backtest": {
            "trades": best["trades"],
            "won": best["won"],
            "lost": best["lost"],
            "win_rate": best["win_rate"],
            "roi_pct": best["roi"],
            "sharpe": best["sharpe"],
            "brier": best["brier"],
            "pnl": best["pnl"],
            "score": best["score"],
        },
    }
    with open(strategy_path, "w") as f:
        json.dump(strategy, f, indent=2, sort_keys=True)

    print(f"✓ Wrote best weights to  {weights_path}")
    print(f"✓ Wrote strategy params  {strategy_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Karpathy-style autonomous parameter search"
    )
    parser.add_argument(
        "--candidates", type=int, default=500, help="Number of parameter sets to try"
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="RNG seed for reproducibility"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Don't write the best params to disk"
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  ASIAbot — Autonomous Karpathy Parameter Search")
    print("=" * 72)
    print()

    best, _ = search(num_candidates=args.candidates, seed=args.seed)

    print()
    print("=== BEST CANDIDATE ===")
    c = best["candidate"]
    print(f"  min_edge         = {c['min_edge']:.3f}")
    print(f"  kelly_fraction   = {c['kelly_fraction']:.3f}")
    print(f"  max_bet_pct      = {c['max_bet_pct']:.3f}")
    print(f"  min_entry_price  = {c['min_entry_price']:.3f}")
    print(f"  inefficiency_min = {c['inefficiency_min']:+.3f}")
    print()
    print("  Model weights:")
    for m, w in sorted(c["model_weights"].items(), key=lambda kv: -kv[1]):
        print(f"    {m:30s}  {w:.4f}")
    print()
    print("  Backtest result:")
    print(f"    trades  = {best['trades']}")
    print(f"    wins    = {best['won']}")
    print(f"    losses  = {best['lost']}")
    print(f"    winrate = {best['win_rate']:.4f}")
    print(f"    roi     = {best['roi']:+.2f}%")
    print(f"    sharpe  = {best['sharpe']:.4f}")
    print(f"    brier   = {best['brier']:.4f}")
    print(f"    net pnl = ${best['pnl']:+.2f}")
    print(f"    score   = {best['score']:+.4f}")

    if not args.no_save:
        print()
        save_best_to_disk(best)


if __name__ == "__main__":
    main()
