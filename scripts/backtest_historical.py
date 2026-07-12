"""Backtest using historical analyses + bets data.

Strategy: For each historical analysis with should_bet=True,
check if the bet would have won by looking at bet outcomes.
"""

import sqlite3
import pandas as pd


def main():
    conn = sqlite3.connect("data/bot.db")

    # === Load analyses ===
    analyses = pd.read_sql(
        """
        SELECT id, market_id, estimated_probability, market_implied_prob,
               edge, recommended_side, recommended_amount, confidence_score,
               should_bet, analyzed_at, adjusted_edge
        FROM analyses
        WHERE should_bet = 1
    """,
        conn,
    )
    print(f"Actionable analyses: {len(analyses)}")
    print(f"  Unique markets: {analyses['market_id'].nunique()}")

    # === Load bets ===
    bets = pd.read_sql("SELECT * FROM bets", conn)
    print(f"Total bets: {len(bets)}")

    # Check status distribution
    print(f"  Status distribution: {dict(bets['status'].value_counts())}")

    # === Merge analyses with bets on market_id ===
    # For each market, find the analysis that led to the bet and the outcome
    if "result_data" in bets.columns:
        bets_with_result = bets[bets["result_data"].notna() & (bets["result_data"] != "")]
        print(f"\nBets with result_data: {len(bets_with_result)}")
        if len(bets_with_result) > 0:
            print(f"  sample result_data: {bets_with_result['result_data'].iloc[0][:200]}")

    # === Historical bet performance ===
    print("\n" + "=" * 60)
    print("HISTORICAL BET PERFORMANCE")
    print("=" * 60)

    # Group by market_id
    market_stats = (
        bets.groupby("market_id")
        .agg(
            n_bets=("id", "count"),
            total_stake=("stake", "sum"),
            total_pnl=("pnl", "sum"),
            first_bet=("placed_at", "min"),
        )
        .reset_index()
    )

    print(f"Markets with bets: {len(market_stats)}")
    print(f"Total stake: ${market_stats['total_stake'].sum():.2f}")
    print(f"Total PnL: ${market_stats['total_pnl'].sum():.2f}")
    print(f"ROI: {market_stats['total_pnl'].sum() / market_stats['total_stake'].sum() * 100:.2f}%")

    # === Edge analysis: what was the avg edge of winning vs losing bets? ===
    print("\n" + "=" * 60)
    print("ANALYSIS-BASED PERFORMANCE")
    print("=" * 60)

    # Join analyses with bets
    merged = pd.merge(
        bets[["market_id", "side", "entry_price", "pnl", "status", "stake", "placed_at"]],
        analyses[
            ["market_id", "estimated_probability", "market_implied_prob", "edge", "confidence_score", "adjusted_edge"]
        ],
        on="market_id",
        how="inner",
    )
    print(f"Merged (bet+analysis): {len(merged)} rows")

    if len(merged) > 0:
        merged["won"] = merged["pnl"] > 0
        print(f"  Won: {merged['won'].sum()}, Lost: {(~merged['won']).sum()}")
        print(f"  Avg edge (won): {merged[merged['won']]['edge'].mean():.4f}")
        print(f"  Avg edge (lost): {merged[~merged['won']]['edge'].mean():.4f}")
        print(f"  Avg adjusted_edge (won): {merged[merged['won']]['adjusted_edge'].mean():.4f}")
        print(f"  Avg adjusted_edge (lost): {merged[~merged['won']]['adjusted_edge'].mean():.4f}")

    # === Brier-score style analysis ===
    print("\n" + "=" * 60)
    print("PREDICTION CALIBRATION")
    print("=" * 60)

    # For analyses with should_bet, look at estimated_probability vs outcome
    # Outcome = won/lost from bets
    calib = pd.merge(
        analyses[
            ["market_id", "estimated_probability", "market_implied_prob", "edge", "recommended_side", "adjusted_edge"]
        ],
        bets[["market_id", "side", "pnl", "stake"]].assign(outcome=lambda x: (x["pnl"] > 0).astype(float)),
        on="market_id",
        how="inner",
    )
    print(f"Calibration data: {len(calib)} rows")

    if len(calib) > 0:
        # Group by predicted probability bucket
        calib["pred_bucket"] = pd.cut(calib["estimated_probability"], bins=10)
        calib_grp = calib.groupby("pred_bucket", observed=True).agg(
            mean_pred=("estimated_probability", "mean"),
            win_rate=("outcome", "mean"),
            count=("outcome", "count"),
        )
        print(calib_grp.to_string())

        # Brier score
        brier = ((calib["estimated_probability"] - calib["outcome"]) ** 2).mean()
        print(f"\nBrier score (analyses): {brier:.4f}")

        # For comparison: naive model always predict overall win rate
        overall_win_rate = calib["outcome"].mean()
        naive_brier = ((overall_win_rate - calib["outcome"]) ** 2).mean()
        print(f"Brier score (naive {overall_win_rate:.3f}): {naive_brier:.4f}")

        # Edge quality
        calib["correct_side"] = ((calib["recommended_side"] == "YES") & (calib["outcome"] == 1)) | (
            (calib["recommended_side"] == "NO") & (calib["outcome"] == 0)
        )
        print(f"\nSide accuracy: {calib['correct_side'].mean() * 100:.1f}%")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
