"""Explore historical bet data for backtest optimization."""
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "..", "data", "bot.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. Bet count & status
c.execute("SELECT status, COUNT(*), COALESCE(SUM(pnl),0), COALESCE(SUM(stake),0) FROM bets GROUP BY status")
print("=== BET STATUS ===")
for row in c.fetchall():
    status, cnt, pnl, staked = row
    print(f"  {status}: {cnt} trades, PnL={pnl:.2f}, Staked={staked:.2f}")

# 2. Side distribution
c.execute("SELECT COALESCE(side,'none'), COUNT(*), COALESCE(AVG(entry_price),0), COALESCE(AVG(stake),0) FROM bets GROUP BY side")
print("\n=== BET SIDE ===")
for row in c.fetchall():
    side, cnt, avg_entry, avg_stake = row
    print(f"  {side}: {cnt} trades, avg_entry={avg_entry:.3f}, avg_stake={avg_stake:.2f}")

# 3. Column names
c.execute("PRAGMA table_info(bets)")
cols = [r[1] for r in c.fetchall()]
print(f"\n=== BETS COLUMNS ===\n  {cols}")

# 4. Sample bets
c.execute("""
    SELECT id, side, stake, entry_price, shares, pnl, status,
           fair_value, expected_value, amount, city, outcome, entry_fee
    FROM bets
    WHERE status IN ('won','lost','closed_early')
    ORDER BY id
    LIMIT 10
""")
print("\n=== SAMPLE SETTLED BETS ===")
for row in c.fetchall():
    print(f"  id={row[0]}, side={row[1]}, stake={row[2]}, entry={row[3]}, shares={row[4]}, pnl={row[5]}, status={row[6]}, fair={row[7]}, ev={row[8]}, amt={row[9]}, city={row[10]}, outcome={row[11]}, fee={row[12]}")

# 5. Analyses table
c.execute("PRAGMA table_info(analyses)")
acols = [r[1] for r in c.fetchall()]
print(f"\n=== ANALYSES COLUMNS ===\n  {acols}")

# 6. Sample analyses
c.execute("""
    SELECT id, market_id, estimated_probability, market_implied_prob,
           edge, raw_edge, adjusted_edge, confidence_score,
           model_predictions
    FROM analyses
    ORDER BY id DESC
    LIMIT 3
""")
print("\n=== SAMPLE ANALYSES ===")
for row in c.fetchall():
    print(f"  id={row[0]}, market={row[1]}, est_prob={row[2]}, implied={row[3]}, edge={row[4]}, raw_edge={row[5]}, adj_edge={row[6]}, conf={row[7]}")
    mp = row[8]
    if mp:
        print(f"    model_predictions={mp[:200]}")

# 7. Check which bets have linked analyses
c.execute("""
    SELECT b.id, b.analysis_id, a.estimated_probability, a.edge, a.model_predictions
    FROM bets b
    LEFT JOIN analyses a ON b.analysis_id = a.id
    WHERE b.status IN ('won','lost','closed_early')
    AND a.model_predictions IS NOT NULL
    LIMIT 5
""")
print("\n=== BETS WITH ANALYSIS + MODEL_PREDICTIONS ===")
for row in c.fetchall():
    print(f"  bet_id={row[0]}, analysis_id={row[1]}, est_prob={row[2]}, edge={row[3]}")
    print(f"    model_pred={row[4][:300] if row[4] else None}")

# 8. Weather markets resolved
c.execute("SELECT status, COUNT(*) FROM weather_markets GROUP BY status")
print("\n=== MARKET STATUS ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 9. Bets with market data (for re-evaluation)
c.execute("""
    SELECT b.id, b.market_id, b.side, b.stake, b.entry_price, b.shares,
           b.pnl, b.status, b.outcome, b.city,
           wm.yes_price, wm.no_price, wm.target_date, wm.city_code
    FROM bets b
    LEFT JOIN weather_markets wm ON b.market_id = wm.id
    WHERE b.status IN ('won','lost','closed_early')
    ORDER BY b.id
    LIMIT 10
""")
print("\n=== BETS + MARKET DATA ===")
for row in c.fetchall():
    print(f"  bet={row[0]}, market={row[1]}, side={row[2]}, stake={row[3]}, entry={row[4]}, pnl={row[6]}, status={row[7]}, outcome={row[8]}, city={row[9]}, yes_p={row[10]}, no_p={row[11]}, target={row[12]}, city_code={row[13]}")

# 10. Total settled bets with non-null stake
c.execute("""
    SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),0),
           COALESCE(SUM(pnl),0)
    FROM bets
    WHERE status IN ('won','lost','closed_early')
    AND stake IS NOT NULL AND stake > 0
""")
row = c.fetchone()
print("\n=== SETTLED BETS WITH STAKE ===")
print(f"  Total: {row[0]}, Won: {row[1]}, PnL: {row[2]:.2f}")

# 11. Edge distribution of bets
c.execute("""
    SELECT 
        CASE 
            WHEN a.edge < 0 THEN '< 0'
            WHEN a.edge < 0.02 THEN '0-2%'
            WHEN a.edge < 0.05 THEN '2-5%'
            WHEN a.edge < 0.10 THEN '5-10%'
            WHEN a.edge < 0.20 THEN '10-20%'
            ELSE '> 20%'
        END as edge_bucket,
        COUNT(*),
        SUM(CASE WHEN b.pnl > 0 THEN 1 ELSE 0 END) as wins,
        COALESCE(SUM(b.pnl), 0) as total_pnl
    FROM bets b
    JOIN analyses a ON b.analysis_id = a.id
    WHERE b.status IN ('won','lost','closed_early')
    AND b.stake IS NOT NULL AND b.stake > 0
    GROUP BY edge_bucket
    ORDER BY edge_bucket
""")
print("\n=== EDGE DISTRIBUTION ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} trades, {row[2]} wins, PnL={row[3]:.2f}")

conn.close()
