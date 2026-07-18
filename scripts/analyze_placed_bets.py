"""Focused analysis on ACTUALLY PLACED bets only."""
import sqlite3
import pandas as pd


def main():
    conn = sqlite3.connect("data/bot.db")

    bets = pd.read_sql("SELECT * FROM bets", conn)
    # Only real bets (not rejected)
    placed = bets[bets["status"].isin(["won", "lost", "closed_early", "placed"])].copy()
    print(f"Placed bets: {len(placed)}")
    print(f"  Status: {dict(placed['status'].value_counts())}")
    print()

    # PnL breakdown
    print("=" * 60)
    print("PnL BREAKDOWN (placed bets only)")
    print("=" * 60)
    won = placed[placed["status"] == "won"]
    lost = placed[placed["status"] == "lost"]
    closed = placed[placed["status"] == "closed_early"]
    print(f"  Won: {len(won)}, avg_pnl: ${won['pnl'].mean():.2f}" if len(won) else "  Won: 0")
    print(f"  Lost: {len(lost)}, avg_pnl: ${lost['pnl'].mean():.2f}" if len(lost) else "  Lost: 0")
    print(f"  Closed early: {len(closed)}, avg_pnl: ${closed['pnl'].mean():.2f}" if len(closed) else "  Closed early: 0")
    print(f"  Total PnL: ${placed['pnl'].sum():.2f}")

    if "stake" in placed.columns:
        total_stake = placed["stake"].sum()
        if total_stake > 0:
            print(f"  Total stake: ${total_stake:.2f}")
            print(f"  ROI: {placed['pnl'].sum() / total_stake * 100:.2f}%")

    # Side analysis
    print(f"\n  Side distribution: {dict(placed['side'].value_counts())}")

    # City analysis
    if "city" in placed.columns:
        city_perf = placed.groupby("city").agg(
            n=("id", "count"),
            pnl=("pnl", "sum"),
            win_rate=("pnl", lambda x: (x > 0).mean()),
        ).sort_values("pnl", ascending=False)
        print(f"\n  Per-city performance:")
        print(city_perf.to_string())

    # === Match with analyses for edge calibration ===
    print("\n" + "=" * 60)
    print("EDGE vs OUTCOME (placed bets)")
    print("=" * 60)

    analyses = pd.read_sql("""
        SELECT market_id, estimated_probability, market_implied_prob, edge, adjusted_edge
        FROM analyses WHERE should_bet = 1
    """, conn)

    # Deduplicate analyses per market_id (keep first per market)
    analyses_dedup = analyses.drop_duplicates(subset="market_id", keep="first")

    merged = pd.merge(
        placed[["market_id", "side", "pnl", "status", "stake", "entry_price"]],
        analyses_dedup,
        on="market_id",
        how="inner",
    )
    print(f"Matched: {len(merged)}")
    if len(merged) > 0:
        merged["won"] = merged["pnl"] > 0
        print(f"  Win rate: {merged['won'].mean()*100:.1f}%")
        print(f"  Avg edge (won): {merged[merged['won']]['edge'].mean():.4f}")
        print(f"  Avg edge (lost): {merged[~merged['won']]['edge'].mean():.4f}" if len(merged[~merged['won']]) else "  No losses")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
