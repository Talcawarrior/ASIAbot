"""Deep explore of bet data for backtest."""

import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "..", "data", "bot.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

# Check which columns have actual data
c.execute("SELECT stake, stake_amount, amount, entry_price, entry_fee, shares, pnl FROM bets WHERE id = 1")
print("Bet #1:", c.fetchone())

# Count bets with actual stake data
c.execute("SELECT COUNT(*) FROM bets WHERE stake IS NOT NULL AND stake > 0")
print("Bets with stake>0:", c.fetchone()[0])

c.execute("SELECT COUNT(*) FROM bets WHERE stake_amount IS NOT NULL AND stake_amount > 0")
print("Bets with stake_amount>0:", c.fetchone()[0])

c.execute("SELECT COUNT(*) FROM bets WHERE amount IS NOT NULL AND amount > 0")
print("Bets with amount>0:", c.fetchone()[0])

# Get total PnL
c.execute("SELECT SUM(pnl) FROM bets WHERE status IN ('won','lost','closed_early')")
r = c.fetchone()
print(f"Total PnL: {r[0]}")

# How many bets have valid data for backtest
c.execute("""
    SELECT COUNT(*) FROM bets b
    JOIN analyses a ON b.analysis_id = a.id
    WHERE b.status IN ('won','lost','closed_early')
    AND b.entry_price IS NOT NULL
    AND a.estimated_probability IS NOT NULL
    AND a.edge IS NOT NULL
""")
print(f"Bets with entry_price + analysis edge: {c.fetchone()[0]}")

# Sample with edge and outcome
c.execute("""
    SELECT b.id, b.side, b.entry_price, b.pnl, b.status, b.outcome,
           a.estimated_probability, a.edge, a.raw_edge, a.market_implied_prob,
           b.shares, b.amount
    FROM bets b
    JOIN analyses a ON b.analysis_id = a.id
    WHERE b.status IN ('won','lost','closed_early')
    AND b.entry_price IS NOT NULL
    ORDER BY b.id
    LIMIT 20
""")
print("\nBets with analysis:")
for r in c.fetchall():
    print(
        f"  id={r[0]}, side={r[1]}, entry={r[2]}, pnl={r[3]}, status={r[4]}, outcome={r[5]}, est_prob={r[6]:.4f}, edge={r[7]:.4f}, raw={r[8]:.4f}, implied={r[9]:.4f}, shares={r[10]}, amount={r[11]}"
    )

# Won bets: what's the payout relationship?
c.execute("""
    SELECT b.entry_price, b.shares, b.amount, b.pnl
    FROM bets b
    WHERE b.status = 'won'
    AND b.entry_price IS NOT NULL AND b.entry_price > 0
    LIMIT 10
""")
print("\nWon bets (entry, shares, amount, pnl):")
for r in c.fetchall():
    payout = r[1] if r[1] else 0
    cost = r[2] if r[2] else 0
    print(f"  entry={r[0]:.4f}, shares={r[1]}, amount={r[2]}, pnl={r[3]:.2f}")

# Lost bets
c.execute("""
    SELECT b.entry_price, b.shares, b.amount, b.pnl
    FROM bets b
    WHERE b.status = 'lost'
    AND b.entry_price IS NOT NULL AND b.entry_price > 0
    LIMIT 10
""")
print("\nLost bets:")
for r in c.fetchall():
    print(f"  entry={r[0]:.4f}, shares={r[1]}, amount={r[2]}, pnl={r[3]:.2f}")

# Closed early
c.execute("""
    SELECT b.entry_price, b.shares, b.amount, b.pnl, b.close_reason
    FROM bets b
    WHERE b.status = 'closed_early'
    AND b.entry_price IS NOT NULL AND b.entry_price > 0
    LIMIT 10
""")
print("\nClosed early bets:")
for r in c.fetchall():
    print(f"  entry={r[0]:.4f}, shares={r[1]}, amount={r[2]}, pnl={r[3]:.2f}, reason={r[4]}")

# Summary of settled bets
c.execute("""
    SELECT status, COUNT(*), 
           COALESCE(SUM(pnl),0), COALESCE(AVG(pnl),0),
           COALESCE(AVG(entry_price),0)
    FROM bets
    WHERE status IN ('won','lost','closed_early')
    AND entry_price IS NOT NULL AND entry_price > 0
    GROUP BY status
""")
print("\n=== SETTLED BETS SUMMARY ===")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} trades, total_pnl={r[2]:.2f}, avg_pnl={r[3]:.2f}, avg_entry={r[4]:.4f}")

conn.close()
