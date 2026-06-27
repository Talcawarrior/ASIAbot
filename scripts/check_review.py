#!/usr/bin/env python3
"""Check review findings against current DB state."""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

print("=== PORTFOLIO ===")
c.execute(
    "SELECT total_value, cash_balance, total_realized_pnl, total_won, total_lost FROM portfolio WHERE id=1"
)
row = c.fetchone()
if row:
    print(
        f"  total_value={row[0]}, cash_balance={row[1]}, realized_pnl={row[2]}, won={row[3]}, lost={row[4]}"
    )

print("\n=== CLOSED_EARLY BETS ===")
c.execute(
    "SELECT COUNT(*), COALESCE(SUM(pnl), 0), COALESCE(SUM(realized_pnl), 0) FROM bets WHERE status='closed_early'"
)
row = c.fetchone()
print(f"  count={row[0]}, sum_pnl={row[1]}, sum_realized={row[2]}")

print("\n=== SAMPLE closed_early BETS ===")
c.execute(
    "SELECT id, side, entry_price, current_price, pnl, realized_pnl, close_reason FROM bets WHERE status='closed_early' ORDER BY id DESC LIMIT 5"
)
for r in c.fetchall():
    print(
        f"  bet#{r[0]}: side={r[1]}, entry={r[2]}, current={r[3]}, pnl={r[4]}, realized={r[5]}, reason={r[6]}"
    )

print("\n=== ALL CLOSED BETS REALIZED ===")
c.execute(
    "SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM bets WHERE status IN ('won','lost','settled','closed_early')"
)
row = c.fetchall()
for r in row:
    print(f"  count={r[0]}, net_pnl={r[1]}")

print("\n=== STATUS COUNTS ===")
c.execute("SELECT status, COUNT(*) FROM bets GROUP BY status ORDER BY COUNT(*) DESC")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== MODEL PERFORMANCE ===")
c.execute(
    "SELECT model_name, brier_score, accuracy, num_predictions FROM model_performance LIMIT 10"
)
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]}: brier={r[1]}, acc={r[2]}, n={r[3]}")
else:
    print("  (empty)")

print("\n=== OPEN BET COUNT ===")
c.execute(
    "SELECT COUNT(*) FROM bets WHERE status IN ('active', 'open', 'placed', 'pending')"
)
print(f"  {c.fetchone()[0]}")

conn.close()
