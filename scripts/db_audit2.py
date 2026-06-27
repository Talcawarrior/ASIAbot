#!/usr/bin/env python3
"""Daily bet count analysis — proving the profit math."""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

print("=" * 70)
print("DAILY BET COUNTS (all time)")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day, 
           COUNT(*) as total_opened,
           SUM(CASE WHEN status IN ('active','open','placed','pending') THEN 1 ELSE 0 END) as still_open,
           SUM(CASE WHEN settled_at IS NOT NULL OR closed_at IS NOT NULL THEN 1 ELSE 0 END) as closed,
           SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as day_pnl,
           SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as day_won,
           SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END) as day_lost
    FROM bets 
    WHERE placed_at IS NOT NULL
    GROUP BY DATE(placed_at)
    ORDER BY day
""")
total_bets_all = 0
for row in c.fetchall():
    day, total, still_open, closed, pnl, won, lost = row
    total_bets_all += total
    print(
        f"  {day}: {total:4d} opened, {closed:4d} closed, PnL=${pnl:,.2f} (won=${won:,.2f} lost=${lost:,.2f})"
    )

print(f"\n  TOTAL BETS: {total_bets_all}")

print()
print("=" * 70)
print("BET SIZES ANALYSIS")
print("=" * 70)
c.execute(
    "SELECT MIN(amount), MAX(amount), AVG(amount), SUM(amount) FROM bets WHERE amount > 0"
)
mn, mx, avg, total_amt = c.fetchone()
print(f"  Min bet: ${mn:,.2f}")
print(f"  Max bet: ${mx:,.2f}")
print(f"  Avg bet: ${avg:,.2f}")
print(f"  Total bet amount: ${total_amt:,.2f}")

# How many bets at max ($30)?
c.execute("SELECT COUNT(*) FROM bets WHERE amount >= 29.99")
at_max = c.fetchone()[0]
print(f"  Bets at $30 (max): {at_max}")

c.execute("SELECT COUNT(*) FROM bets WHERE amount >= 29.00")
near_max = c.fetchone()[0]
print(f"  Bets at $29+: {near_max}")

print()
print("=" * 70)
print("25% LIMIT CHECK")
print("=" * 70)
c.execute(
    "SELECT initial_balance, current_balance FROM portfolio ORDER BY id DESC LIMIT 1"
)
row = c.fetchone()
if row:
    initial, current = row
    max_bet_pct = 25
    max_bet_25 = current * max_bet_pct / 100
    print(f"  Current balance: ${current:,.2f}")
    print(f"  25% of balance: ${max_bet_25:,.2f}")
    print(f"  Actual bet sizes: ~${avg:,.2f}")
    print(f"  Bet size / 25% limit: {avg / max_bet_25 * 100:.1f}%")
    print(f"  Number of 25%-size bets possible: {int(current / (current * 0.25))}")

print()
print("=" * 70)
print("PROFIT MATH BREAKDOWN")
print("=" * 70)
c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL)"
)
total_closed = c.fetchone()[0]
c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL) AND pnl > 0"
)
won_count = c.fetchone()[0]
c.execute(
    "SELECT COUNT(*) FROM bets WHERE (settled_at IS NOT NULL OR closed_at IS NOT NULL) AND pnl < 0"
)
lost_count = c.fetchone()[0]
c.execute("SELECT SUM(pnl) FROM bets WHERE pnl > 0")
total_won = c.fetchone()[0]
c.execute("SELECT SUM(pnl) FROM bets WHERE pnl < 0")
total_lost = c.fetchone()[0]
c.execute("SELECT SUM(pnl) FROM bets WHERE pnl IS NOT NULL")
total_pnl = c.fetchone()[0]

win_rate = won_count / total_closed * 100 if total_closed else 0
avg_win = total_won / won_count if won_count else 0
avg_loss = total_lost / lost_count if lost_count else 0

print(f"  Total closed bets: {total_closed}")
print(f"  Wins: {won_count} ({win_rate:.1f}%)")
print(f"  Losses: {lost_count} ({100 - win_rate:.1f}%)")
print(f"  Gross wins: ${total_won:,.2f}")
print(f"  Gross losses: ${total_lost:,.2f}")
print(f"  Net PnL: ${total_pnl:,.2f}")
print(f"  Avg win: ${avg_win:,.2f}")
print(f"  Avg loss: ${avg_loss:,.2f}")
print(
    f"  Profit factor: {total_won / abs(total_lost):.2f}"
    if total_lost
    else "  Profit factor: N/A"
)
print(f"  Avg PnL per bet: ${total_pnl / total_closed:,.2f}" if total_closed else "")
print(f"  Avg PnL per day (10 days): ${total_pnl / 10:,.2f}")

print()
print("=" * 70)
print("WHERE DOES $125K COME FROM?")
print("=" * 70)
c.execute("""
    SELECT close_reason, COUNT(*) as cnt, 
           SUM(pnl) as pnl, 
           AVG(pnl) as avg_pnl,
           SUM(amount) as total_amount,
           AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win_pnl,
           AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss_pnl
    FROM bets 
    WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL
    GROUP BY close_reason
    ORDER BY pnl DESC
""")
for row in c.fetchall():
    reason, cnt, pnl, avg_pnl, amt, avg_win, avg_loss = row
    reason = reason or "unsettled"
    print(f"\n  {reason}:")
    print(f"    Count: {cnt}")
    print(f"    Total PnL: ${pnl:,.2f}")
    print(f"    Avg PnL: ${avg_pnl:,.2f}")
    print(f"    Total bet: ${amt:,.2f}")
    print(f"    Avg win: ${avg_win:,.2f}" if avg_win else "")
    print(f"    Avg loss: ${avg_loss:,.2f}" if avg_loss else "")

print()
print("=" * 70)
print("WIN RATE vs EXIT TYPE")
print("=" * 70)
c.execute("""
    SELECT close_reason, 
           SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
           ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_pct
    FROM bets 
    WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL
    GROUP BY close_reason
    ORDER BY wins DESC
""")
for row in c.fetchall():
    reason, wins, losses, wpct = row
    reason = reason or "unsettled"
    print(f"  {reason}: {wins}W / {losses}L ({wpct}% win)")

print()
print("=" * 70)
print("ACCOUNTING TABLE")
print("=" * 70)
try:
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"  Tables: {tables}")

    if "accounting" in tables:
        c.execute("PRAGMA table_info(accounting)")
        cols = [r[1] for r in c.fetchall()]
        print(f"  Accounting columns: {cols}")
        c.execute("SELECT * FROM accounting ORDER BY rowid DESC LIMIT 5")
        for r in c.fetchall():
            print(f"  {r}")
    else:
        print("  No accounting table")
except Exception as e:
    print(f"  Error: {e}")

conn.close()
print("\nDONE.")
