#!/usr/bin/env python3
"""Settlement timing and concurrent exposure analysis."""

import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# How fast do bets settle?
print("=" * 70)
print("SETTLEMENT TIMING: How fast do bets close?")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day,
           AVG(CAST((julianday(COALESCE(settled_at, closed_at)) - julianday(placed_at)) * 24 AS REAL)) as avg_hours,
           MIN(CAST((julianday(COALESCE(settled_at, closed_at)) - julianday(placed_at)) * 24 AS REAL)) as min_hours,
           MAX(CAST((julianday(COALESCE(settled_at, closed_at)) - julianday(placed_at)) * 24 AS REAL)) as max_hours,
           COUNT(*) as cnt
    FROM bets 
    WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL
    GROUP BY day
""")
for r in c.fetchall():
    print(f"  {r[0]}: avg={r[1]:.1f}h, min={r[2]:.1f}h, max={r[3]:.1f}h, count={r[4]}")

# Close reason breakdown
print("\n--- CLOSE REASON TIMING ---")
c.execute("""
    SELECT close_reason,
           AVG(CAST((julianday(COALESCE(settled_at, closed_at)) - julianday(placed_at)) * 24 AS REAL)) as avg_hours,
           COUNT(*) as cnt
    FROM bets 
    WHERE settled_at IS NOT NULL OR closed_at IS NOT NULL
    GROUP BY close_reason
""")
for r in c.fetchall():
    print(f"  {r[0] or 'none'}: avg {r[1]:.1f}h to close, {r[2]} bets")

# Simulate concurrent exposure on Jun 16 with 5-min windows
print("\n" + "=" * 70)
print("SIMULATED EXPOSURE ON JUN 16 (5-min windows)")
print("=" * 70)
c.execute("""
    SELECT placed_at, amount, COALESCE(settled_at, closed_at) as end_time
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY placed_at
""")
all_bets = c.fetchall()

# For each 5-min window, calculate concurrent exposure
start = datetime(2026, 6, 16, 18, 0)
end = datetime(2026, 6, 17, 0, 0)

max_exp = 0
max_exp_time = None
window_data = []

for i in range(0, 360, 5):  # every 5 min
    window_time = start + timedelta(minutes=i)
    active_amount = 0
    active_count = 0
    for bet in all_bets:
        bet_start = datetime.fromisoformat(bet[0])
        bet_end = (
            datetime.fromisoformat(bet[2])
            if bet[2]
            else window_time + timedelta(hours=1)
        )
        if bet_start <= window_time <= bet_end:
            active_amount += bet[1]
            active_count += 1
    if active_amount > max_exp:
        max_exp = active_amount
        max_exp_time = window_time
    if i % 30 == 0:  # every 30 min
        portfolio_est = 10000 + (active_amount * 0.25)  # rough estimate
        print(
            f"  {window_time.strftime('%H:%M')}: {active_count:3d} active bets, ${active_amount:>8,.2f} exposure"
        )

print(f"\n  MAX exposure: ${max_exp:,.2f} at {max_exp_time}")

# What was the ACTUAL portfolio value at that point?
print("\n" + "=" * 70)
print("PORTFOLIO GROWTH: When did capital allow more bets?")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day,
           SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END) as cum_pnl,
           COUNT(*) as total_bets,
           SUM(CASE WHEN settled_at IS NOT NULL OR closed_at IS NOT NULL THEN amount ELSE 0 END) as settled_amount
    FROM bets GROUP BY day ORDER BY day
""")
running_pnl = 10000
for r in c.fetchall():
    running_pnl += r[1]
    max_exp_25 = running_pnl * 0.25
    max_bets_at_30 = int(max_exp_25 / 30)
    print(
        f"  {r[0]}: PnL=${r[1]:>10,.2f}, cum_portfolio=${running_pnl:>10,.2f}, 25%=${max_exp_25:>8,.2f}, max_concurrent_bets={max_bets_at_30}"
    )

# Check: how many bets were open at MAX EXPOSURE moment on Jun 16?
print("\n" + "=" * 70)
print("CLOSED_EARLY: How fast? (first 20 Jun 16 bets)")
print("=" * 70)
c.execute("""
    SELECT id, amount, placed_at, closed_at, close_reason, pnl,
           CAST((julianday(closed_at) - julianday(placed_at)) * 24 * 60 AS REAL) as minutes_to_close
    FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    AND closed_at IS NOT NULL
    ORDER BY placed_at
    LIMIT 20
""")
for r in c.fetchall():
    print(
        f"  ID={r[0]}, amt=${r[1]:.2f}, placed={r[2]}, closed={r[3]}, reason={r[4]}, pnl=${r[5]:.2f}, lifetime={r[6]:.0f}min"
    )

# Key question: were there many bets open simultaneously?
print("\n" + "=" * 70)
print("HOW MANY BETS WERE SIMULTANEOUSLY OPEN ON JUN 16?")
print("=" * 70)
c.execute("""
    SELECT id, placed_at, COALESCE(settled_at, closed_at, '2026-06-18') as end_time, amount
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY placed_at
""")
bets = c.fetchall()
# Check at each bet's placement moment: how many other bets are open?
sample_indices = [0, 50, 100, 200, 400, 700, 1000, 1400]
for idx in sample_indices:
    if idx >= len(bets):
        continue
    target = bets[idx]
    target_start = datetime.fromisoformat(target[1])
    concurrent = 0
    concurrent_amt = 0
    for b in bets:
        b_start = datetime.fromisoformat(b[1])
        b_end = datetime.fromisoformat(b[2])
        if b_start <= target_start <= b_end:
            concurrent += 1
            concurrent_amt += b[3]
    print(
        f"  Bet ID={target[0]} at {target[1][:19]}: {concurrent} concurrent bets, ${concurrent_amt:,.2f} exposure"
    )

conn.close()
print("\nDONE.")
