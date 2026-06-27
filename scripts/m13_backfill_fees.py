#!/usr/bin/env python3
"""M13 backfill: deduct Polymarket fees from existing closed_early bets.

Early exits were not charging the 2% fee on profit. This script:
1. Calculates the fee that SHOULD have been charged for each profitable closed_early bet
2. Deducts total uncharged fees from portfolio.cash_balance
3. Adjusts portfolio.total_realized_pnl and portfolio.total_value accordingly
"""

import sqlite3

DB = "data/bot.db"
FEE_RATE = 0.02

conn = sqlite3.connect(DB)
c = conn.cursor()

# Find all profitable closed_early bets
c.execute("""
    SELECT id, amount, pnl, realized_pnl, entry_price, current_price, shares
    FROM bets
    WHERE status = 'closed_early' AND pnl > 0
""")
profitable_bets = c.fetchall()
print(f"Found {len(profitable_bets)} profitable closed_early bets")

# Calculate fee that should have been charged
total_fee_owed = 0.0
bet_fees = []
for bet_id, amount, pnl, realized, entry, current, shares in profitable_bets:
    # Fee = 2% of profit
    fee = round(max(0.0, pnl) * FEE_RATE, 2)
    total_fee_owed += fee
    bet_fees.append((bet_id, fee))

print(f"Total fee that should have been charged: ${total_fee_owed:.2f}")

# Get current portfolio
c.execute(
    "SELECT cash_balance, total_value, total_realized_pnl FROM portfolio WHERE id=1"
)
cash, total_value, realized_pnl = c.fetchone()
print("\nBefore:")
print(f"  cash_balance: ${cash:.2f}")
print(f"  total_value: ${total_value:.2f}")
print(f"  total_realized_pnl: ${realized_pnl:.2f}")

# Deduct fees from portfolio
new_cash = round(cash - total_fee_owed, 2)
new_total_value = new_cash  # closed bets = no unrealized
new_realized_pnl = round(realized_pnl - total_fee_owed, 2)

c.execute(
    """
    UPDATE portfolio SET
        cash_balance = ?,
        total_value = ?,
        total_realized_pnl = ?
    WHERE id = 1
""",
    (new_cash, new_total_value, new_realized_pnl),
)

# Also update individual bet pnl values (subtract fee)
for bet_id, fee in bet_fees:
    c.execute(
        """
        UPDATE bets SET
            realized_pnl = round(realized_pnl - ?, 2),
            pnl = round(pnl - ?, 2)
        WHERE id = ?
    """,
        (fee, fee, bet_id),
    )

conn.commit()

# Verify
c.execute(
    "SELECT cash_balance, total_value, total_realized_pnl FROM portfolio WHERE id=1"
)
cash2, tv2, rp2 = c.fetchone()
print("\nAfter:")
print(f"  cash_balance: ${cash2:.2f} (was ${cash:.2f}, diff: ${cash2 - cash:.2f})")
print(
    f"  total_value: ${tv2:.2f} (was ${total_value:.2f}, diff: ${tv2 - total_value:.2f})"
)
print(
    f"  total_realized_pnl: ${rp2:.2f} (was ${realized_pnl:.2f}, diff: ${rp2 - realized_pnl:.2f})"
)

# Verify cash reconciliation
c.execute(
    "SELECT COALESCE(SUM(amount), 0) FROM bets WHERE status IN ('active','open','placed','pending')"
)
open_exp = c.fetchone()[0]
expected_cash_formula = round(10000 + rp2 - open_exp, 2)
print("\nReconciliation check:")
print(
    f"  expected_cash = initial(10000) + realized({rp2:.2f}) - open({open_exp:.2f}) = {expected_cash_formula:.2f}"
)
print(f"  actual_cash = {cash2:.2f}")
print(f"  gap = ${round(cash2 - expected_cash_formula, 2)}")

conn.close()
print("\nBackfill complete!")
