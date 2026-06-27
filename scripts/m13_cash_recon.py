#!/usr/bin/env python3
"""M13: Cash reconciliation - find the $1239 gap."""

import json
import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

c.execute("SELECT cash_balance, initial_value FROM portfolio WHERE id=1")
cash, initial = c.fetchone()

# bet.amount = total ladder amount (may include unfilled rungs)
# actual locked = sum of filled amounts only
c.execute("""
    SELECT id, amount, ladder_data, status
    FROM bets WHERE status IN ('active', 'open', 'placed', 'pending')
""")
open_bets = c.fetchall()

total_amount = 0.0
total_filled = 0.0
ladder_diff = 0.0
for bet_id, amount, ladder_data, status in open_bets:
    total_amount += amount or 0.0
    if ladder_data:
        try:
            ladder = (
                json.loads(ladder_data) if isinstance(ladder_data, str) else ladder_data
            )
            if isinstance(ladder, list):
                filled = sum(
                    float(r.get("shares", r.get("size", r.get("amount", 0))))
                    for r in ladder
                    if r.get("status") == "filled"
                )
                pending = sum(
                    float(r.get("size", r.get("amount", 0)))
                    for r in ladder
                    if r.get("status") == "pending"
                )
                total_filled += filled if filled > 0 else amount
                ladder_diff += pending
            else:
                total_filled += amount
        except Exception:
            total_filled += amount
    else:
        total_filled += amount

print(f"Portfolio cash: {cash}")
print(f"Initial: {initial}")
print(f"\nOpen bets: {len(open_bets)}")
print(f"Total bet.amount (includes unfilled ladder): {round(total_amount, 2)}")
print(f"Total actually filled (locked cash): {round(total_filled, 2)}")
print(f"Ladder pending (NOT debited yet): {round(ladder_diff, 2)}")
print(
    f"\nExpected cash = initial + realized - amount_based = {round(initial + 0 - total_amount, 2)}"
)
print(
    f"Expected cash = initial + realized - filled_based = {round(initial + 0 - total_filled, 2)}"
)

# The proper formula:
c.execute(
    "SELECT COALESCE(SUM(pnl), 0) FROM bets WHERE status IN ('won','lost','settled','closed_early')"
)
realized = c.fetchone()[0]
print(f"\nRealized PnL: {realized}")
print(
    f"Gap if using bet.amount: {round(cash - (initial + realized - total_amount), 2)}"
)
print(
    f"Gap if using filled:     {round(cash - (initial + realized - total_filled), 2)}"
)

# Sample a few open bets to see ladder structure
print("\nSample open bets with ladders:")
c.execute("""
    SELECT id, amount, ladder_data FROM bets
    WHERE status IN ('active', 'open', 'placed', 'pending')
    AND ladder_data IS NOT NULL
    LIMIT 3
""")
for bet_id, amount, ld in c.fetchall():
    ladder = json.loads(ld) if isinstance(ld, str) else ld
    filled_sum = sum(
        float(r.get("shares", r.get("size", r.get("amount", 0))))
        for r in ladder
        if r.get("status") == "filled"
    )
    pending_sum = sum(
        float(r.get("size", r.get("amount", 0)))
        for r in ladder
        if r.get("status") == "pending"
    )
    print(
        f"  bet#{bet_id}: amount={amount}, filled={round(filled_sum, 2)}, pending={round(pending_sum, 2)}"
    )

conn.close()
