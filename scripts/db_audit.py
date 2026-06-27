#!/usr/bin/env python3
"""Quick DB audit for profit math analysis."""

import sqlite3
from database.models import OPEN_BET_STATUSES

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

print("=" * 60)
print("BET COUNT BY STATUS")
print("=" * 60)
for status in list(OPEN_BET_STATUSES) + ["won", "lost", "rejected"]:
    c.execute("SELECT COUNT(*) FROM bets WHERE status=?", (status,))
    print(f"  {status}: {c.fetchone()[0]}")

print()
print("=" * 60)
print("CLOSED BETS (settled_at OR closed_at IS NOT NULL)")
print("=" * 60)
c.execute(
    "SELECT COUNT(*) FROM bets WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL"
)
total_closed = c.fetchone()[0]
print(f"  Total closed: {total_closed}")

c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL) AND pnl > 0"
)
won_count = c.fetchone()[0]
print(f"  Won (pnl > 0): {won_count}")

c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL) AND pnl < 0"
)
lost_count = c.fetchone()[0]
print(f"  Lost (pnl < 0): {lost_count}")

c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL) AND pnl = 0"
)
even_count = c.fetchone()[0]
print(f"  Even (pnl = 0): {even_count}")

print()
print("=" * 60)
print("PNL BREAKDOWN")
print("=" * 60)
c.execute("SELECT SUM(pnl) FROM bets WHERE pnl IS NOT NULL")
total_pnl = c.fetchone()[0]
print(f"  Total PnL (all): ${total_pnl:,.2f}")

c.execute("SELECT SUM(pnl) FROM bets WHERE pnl > 0")
total_won = c.fetchone()[0]
print(f"  Total won (gross): ${total_won:,.2f}")

c.execute("SELECT SUM(pnl) FROM bets WHERE pnl < 0")
total_lost = c.fetchone()[0]
print(f"  Total lost (gross): ${total_lost:,.2f}")

print()
print("=" * 60)
print("BET AMOUNTS & SIZES")
print("=" * 60)
c.execute("SELECT SUM(amount) FROM bets")
total_bet = c.fetchone()[0]
print(f"  Total bet amount: ${total_bet:,.2f}")

c.execute("SELECT AVG(amount) FROM bets")
avg_all = c.fetchone()[0]
print(f"  Avg bet (all): ${avg_all:,.2f}")

c.execute(
    "SELECT AVG(amount) FROM bets WHERE status IN ('active','open','placed','pending')"
)
avg_open = c.fetchone()[0]
print(f"  Avg open bet: ${avg_open:,.2f}")

c.execute(
    "SELECT AVG(amount) FROM bets WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL"
)
avg_closed = c.fetchone()[0]
print(f"  Avg closed bet: ${avg_closed:,.2f}")

c.execute("SELECT MAX(amount) FROM bets")
max_bet = c.fetchone()[0]
print(f"  Max bet: ${max_bet:,.2f}")

print()
print("=" * 60)
print("DAILY BET COUNTS (last 14 days)")
print("=" * 60)
c.execute("""
    SELECT DATE(created_at) as day, COUNT(*) as cnt, 
           SUM(CASE WHEN settled_at IS NOT NULL OR closed_at IS NOT NULL THEN 1 ELSE 0 END) as closed_cnt,
           SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as day_pnl
    FROM bets 
    WHERE created_at >= DATE('now', '-14 days')
    GROUP BY DATE(created_at)
    ORDER BY day
""")
for row in c.fetchall():
    day, cnt, closed, pnl = row
    print(f"  {day}: {cnt} bets opened, {closed} closed, PnL=${pnl:,.2f}")

print()
print("=" * 60)
print("PORTFOLIO BALANCE")
print("=" * 60)
c.execute(
    "SELECT initial_balance, current_balance FROM portfolio ORDER BY id DESC LIMIT 1"
)
row = c.fetchone()
if row:
    print(f"  Initial: ${row[0]:,.2f}")
    print(f"  Current: ${row[1]:,.2f}")
    print(f"  PnL: ${row[1] - row[0]:,.2f}")

print()
print("=" * 60)
print("WIN RATE & EXPECTED VALUE")
print("=" * 60)
if total_closed > 0:
    win_rate = won_count / total_closed * 100
    avg_win = total_won / won_count if won_count else 0
    avg_loss = total_lost / lost_count if lost_count else 0
    ev_per_bet = total_pnl / total_closed
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  Avg win: ${avg_win:,.2f}")
    print(f"  Avg loss: ${avg_loss:,.2f}")
    print(f"  EV per bet: ${ev_per_bet:,.2f}")
    print(f"  ROI: {(total_pnl / total_bet * 100) if total_bet else 0:.1f}%")

print()
print("=" * 60)
print("EXIT TYPE BREAKDOWN")
print("=" * 60)
c.execute("""
    SELECT close_reason, COUNT(*) as cnt, SUM(pnl) as pnl 
    FROM bets 
    WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL
    GROUP BY close_reason
    ORDER BY cnt DESC
""")
for row in c.fetchall():
    reason, cnt, pnl = row
    print(f"  {reason or 'unsettled'}: {cnt} bets, PnL=${pnl:,.2f}")

print()
print("=" * 60)
print("FIRST & LAST BET DATES")
print("=" * 60)
c.execute("SELECT MIN(created_at), MAX(created_at) FROM bets")
first, last = c.fetchone()
print(f"  First bet: {first}")
print(f"  Last bet: {last}")

print()
print("=" * 60)
print("ACCOUNTING TABLE")
print("=" * 60)
try:
    c.execute("SELECT * FROM accounting ORDER BY created_at DESC LIMIT 10")
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    print(f"  Columns: {cols}")
    for r in rows:
        print(f"  {r}")
except Exception:
    print("  No accounting table")

conn.close()
print("\nDONE.")
