"""Validate data quality: ensemble accuracy, brier scores, backtest feasibility."""

import sqlite3
import pandas as pd
import numpy as np


def main():
    conn = sqlite3.connect("data/bot.db")

    # === 1. Ensemble accuracy vs actuals ===
    print("=" * 60)
    print("1. ENSEMBLE ACCURACY vs ACTUALS")
    print("=" * 60)
    cal = pd.read_sql("SELECT * FROM historical_calibrations", conn)
    ens = (
        cal.groupby(["city", "date", "metric"])
        .agg(
            ensemble_mean=("predicted_value", "mean"),
            actual=("actual_value", "first"),
            n_models=("model", "count"),
        )
        .reset_index()
    )
    ens["abs_error"] = (ens["ensemble_mean"] - ens["actual"]).abs()
    print(f"  City-date-metric combos: {len(ens)}")
    print(f"  Mean absolute error: {ens['abs_error'].mean():.2f}")
    print(f"  Median absolute error: {ens['abs_error'].median():.2f}")
    print(f"  Max absolute error: {ens['abs_error'].max():.2f}")
    within_2 = (ens["abs_error"] <= 2.0).mean() * 100
    within_3 = (ens["abs_error"] <= 3.0).mean() * 100
    print(f"  Within 2C: {within_2:.1f}%")
    print(f"  Within 3C: {within_3:.1f}%")
    print()

    # === 2. Model breakdown ===
    print("=" * 60)
    print("2. PER-MODEL ACCURACY")
    print("=" * 60)
    cal["abs_error"] = (cal["predicted_value"] - cal["actual_value"]).abs()
    model_err = (
        cal.groupby("model")
        .agg(
            mae=("abs_error", "mean"),
            median_ae=("abs_error", "median"),
            count=("abs_error", "count"),
        )
        .sort_values("mae")
    )
    print(model_err.to_string())
    print()

    # === 3. Brier dataset sanity ===
    print("=" * 60)
    print("3. BRIER DATASET SANITY")
    print("=" * 60)
    from data_pipeline.unified_datastore import UnifiedDatastore

    ds = UnifiedDatastore()
    brier = ds.build_brier_dataset()
    print(f"  Rows: {len(brier)}")
    print(
        f"  yes_price: [{brier['yes_price'].min():.4f}, "
        f"{brier['yes_price'].max():.4f}], "
        f"mean={brier['yes_price'].mean():.4f}"
    )
    print(f"  realized_yes: {dict(brier['realized_yes'].value_counts())}")

    # Brier score of a naive model (always predict 0.5)
    naive_brier = ((brier["yes_price"] - brier["realized_yes"]) ** 2).mean()
    print(f"  Brier score (market prices): {naive_brier:.4f}")
    # Random baseline
    np.random.seed(42)
    random_pred = np.random.uniform(0.3, 0.7, len(brier))
    random_brier = ((random_pred - brier["realized_yes"]) ** 2).mean()
    print(f"  Brier score (random 0.3-0.7): {random_brier:.4f}")
    # Optimal baseline (always predict realized proportion)
    p_win = brier["realized_yes"].mean()
    optimal_brier = p_win * (1 - p_win)  # = variance of binary outcome
    print(f"  Brier score (optimal constant {p_win:.3f}): {optimal_brier:.4f}")
    print()

    # === 4. Historical analyses stats ===
    print("=" * 60)
    print("4. HISTORICAL ANALYSES (483K records)")
    print("=" * 60)
    analyses = pd.read_sql("SELECT * FROM analyses", conn)
    print(f"  Total analyses: {len(analyses)}")
    print(f"  should_bet=True count: {analyses['should_bet'].sum()}")
    print(
        f"  confidence_score range: "
        f"[{analyses['confidence_score'].min():.2f}, "
        f"{analyses['confidence_score'].max():.2f}]"
    )
    print(f"  edge range: [{analyses['edge'].min():.4f}, {analyses['edge'].max():.4f}]")
    print(f"  avg edge: {analyses['edge'].mean():.4f}")

    # Unique markets analyzed
    unique_markets = analyses["market_id"].nunique()
    print(f"  Unique markets analyzed: {unique_markets}")
    print()

    # === 5. Can we build a backtest? ===
    print("=" * 60)
    print("5. BACKTEST FEASIBILITY")
    print("=" * 60)
    # Check if analyses have market_id that maps to bets with outcomes
    bet_cols_sql = "PRAGMA table_info(bets)"
    cur = conn.cursor()
    cur.execute(bet_cols_sql)
    bet_cols = [r[1] for r in cur.fetchall()]
    print(f"  bets columns: {bet_cols}")

    # How many analyses had should_bet=True?
    actionable = analyses[analyses["should_bet"] is True]
    print(f"  Actionable analyses (should_bet=True): {len(actionable)}")
    if len(actionable) > 0:
        print(f"  Unique actionable market_ids: {actionable['market_id'].nunique()}")
        print(f"  Recommended sides: {dict(actionable['recommended_side'].value_counts())}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
