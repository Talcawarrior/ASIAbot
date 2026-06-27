#!/usr/bin/env python3
"""One-time migration: sync portfolio.total_realized_pnl from actual bet data."""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Calculate actual realized PnL from all closed bets
c.execute("""
    SELECT 
        COUNT(CASE WHEN pnl > 0 THEN 1 END),
        COUNT(CASE WHEN pnl <= 0 THEN 1 END),
        COALESCE(SUM(pnl), 0.0)
    FROM bets 
    WHERE status IN ('won', 'lost', 'settled', 'closed_early')
""")
won, lost, total_pnl = c.fetchone()
print(f"Actual closed bets: won={won}, lost={lost}, net_pnl={total_pnl}")

# Get current portfolio state
c.execute(
    "SELECT total_value, cash_balance, total_realized_pnl, total_won, total_lost FROM portfolio WHERE id=1"
)
old = c.fetchone()
print(
    f"Old portfolio: total_value={old[0]}, cash={old[1]}, realized_pnl={old[2]}, won={old[3]}, lost={old[4]}"
)

# Update portfolio with actual data
c.execute(
    """
    UPDATE portfolio SET
        total_realized_pnl = ?,
        total_won = ?,
        total_lost = ?
    WHERE id = 1
""",
    (total_pnl, won, lost),
)

# Also fix total_value = cash_balance (correct for open positions not counted)
c.execute("""
    UPDATE portfolio SET
        total_value = cash_balance
    WHERE id = 1
""")

conn.commit()

# Verify
c.execute(
    "SELECT total_value, cash_balance, total_realized_pnl, total_won, total_lost FROM portfolio WHERE id=1"
)
new = c.fetchone()
print(
    f"\nNew portfolio: total_value={new[0]}, cash={new[1]}, realized_pnl={new[2]}, won={new[3]}, lost={new[4]}"
)
print(
    f"Fixed: realized_pnl {old[2]} -> {new[2]}, won {old[3]} -> {new[3]}, lost {old[4]} -> {new[4]}"
)

conn.close()
