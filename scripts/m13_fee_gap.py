#!/usr/bin/env python3
"""Verify: early exit fees not charged = cash gap source."""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Total positive PnL from closed_early bets (fee should be 2% of this)
c.execute("""
    SELECT SUM(pnl) FROM bets
    WHERE status = 'closed_early' AND pnl > 0
""")
profit_sum = c.fetchone()[0] or 0

fee_rate = 0.02
expected_fee_gap = profit_sum * fee_rate

c.execute("SELECT cash_balance FROM portfolio WHERE id=1")
actual_cash = c.fetchone()[0]

c.execute("SELECT initial_value FROM portfolio WHERE id=1")
initial = c.fetchone()[0]

c.execute(
    "SELECT COALESCE(SUM(pnl), 0) FROM bets WHERE status IN ('won','lost','settled','closed_early')"
)
realized = c.fetchone()[0]

c.execute(
    "SELECT COALESCE(SUM(amount), 0) FROM bets WHERE status IN ('active','open','placed','pending')"
)
locked = c.fetchone()[0]

print(f"Closed_early total profit (pnl>0): {round(profit_sum, 2)}")
print(f"Expected uncharged fee (2%): {round(expected_fee_gap, 2)}")
print(f"Actual cash gap: {round(actual_cash - (initial + realized - locked), 2)}")
print(
    f"Match: {abs(expected_fee_gap - (actual_cash - (initial + realized - locked))) < 50}"
)

# Count of won settled bets vs closed_early
c.execute("SELECT COUNT(*) FROM bets WHERE status = 'won'")
won = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE status = 'closed_early' AND pnl > 0")
ce_won = c.fetchone()[0]
print(f"\nSettled won: {won}")
print(f"Closed_early won: {ce_won}")

conn.close()
