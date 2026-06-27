#!/usr/bin/env python3
"""Deep audit: How can 1447 bets at $30 be placed with $10K capital?"""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

print("=" * 70)
print("QUESTION: Jun 16 — 1447 bets × $30 = $43,410. Portfolio = $10,000")
print("How is this possible with 25% exposure limit ($2,500)?")
print("=" * 70)

# 1. Check if bets on Jun 16 are real or test
print("\n--- Jun 16: ALL BETS ---")
c.execute("""
    SELECT id, market_id, city, amount, stake_amount, entry_price, 
           status, placed_at, settled_at, closed_at, pnl, side,
           close_reason
    FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY placed_at
""")
rows = c.fetchall()
print(f"  Total rows: {len(rows)}")

# Check for test-e2e markets
test_count = sum(1 for r in rows if "test" in str(r[1]).lower())
real_count = len(rows) - test_count
print(f"  test-e2e markets: {test_count}")
print(f"  Real markets: {real_count}")

# Sample first 5 and last 5
print("\n  First 5 bets:")
for r in rows[:5]:
    print(
        f"    ID={r[0]}, market={r[1]}, city={r[3]}, amt=${r[4]:.2f}, entry={r[5]:.4f}, status={r[6]}, placed={r[7]}, settled={r[8]}, pnl={r[10]}"
    )

print("\n  Last 5 bets:")
for r in rows[-5:]:
    print(
        f"    ID={r[0]}, market={r[1]}, city={r[3]}, amt=${r[4]:.2f}, entry={r[5]:.4f}, status={r[6]}, placed={r[7]}, settled={r[8]}, pnl={r[10]}"
    )

# 2. Check settlement timing — how fast do bets settle?
print("\n--- SETTLEMENT TIMING (Jun 16 bets) ---")
c.execute("""
    SELECT id, market_id, amount, placed_at, settled_at, closed_at,
           CAST((julianday(COALESCE(settled_at, closed_at)) - julianday(placed_at)) * 24 AS REAL) as hours_to_close,
           close_reason, pnl
    FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    AND (settled_at IS NOT NULL OR closed_at IS NOT NULL)
    ORDER BY placed_at
""")
timing_rows = c.fetchall()
print(f"  Bets with settlement time: {len(timing_rows)}")
if timing_rows:
    hours = [r[6] for r in timing_rows if r[6] is not None]
    if hours:
        print(f"  Min hours to close: {min(hours):.1f}")
        print(f"  Max hours to close: {max(hours):.1f}")
        print(f"  Avg hours to close: {sum(hours) / len(hours):.1f}")
        # How many settled within 1 hour, 2 hours, etc?
        for threshold in [0.5, 1, 2, 4, 8, 12, 24]:
            count = sum(1 for h in hours if h <= threshold)
            print(
                f"  Settled within {threshold}h: {count} ({100 * count / len(hours):.0f}%)"
            )

    # Show first 10 settlement times
    print("\n  First 10 settlement times:")
    for r in timing_rows[:10]:
        print(
            f"    ID={r[0]}, amt=${r[2]:.2f}, placed={r[3]}, settled={r[4] or r[5]}, hours={r[6]:.1f}h, reason={r[7]}, pnl=${r[8]:.2f}"
        )

# 3. Max concurrent exposure per hour on Jun 16
print("\n--- HOURLY EXPOSURE ON JUN 16 ---")
c.execute("""
    SELECT id, amount, placed_at, settled_at, closed_at, status
    FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY placed_at
""")
all_jun16 = c.fetchall()
print(f"  Total Jun 16 bets: {len(all_jun16)}")
total_amount = sum(r[1] for r in all_jun16)
print(f"  Total amount bet: ${total_amount:,.2f}")

# Calculate concurrent exposure at each bet's placement time
# For each bet placed, count how many bets were "open" at that moment
if all_jun16:
    exposure_snapshots = []
    for i, bet in enumerate(all_jun16):
        bet_placed = bet[2]
        bet_amount = bet[1]
        bet_end = bet[4] or bet[3]  # settled_at or closed_at

        # Count bets open at this moment
        concurrent = 0
        concurrent_amount = 0
        for other in all_jun16:
            other_placed = other[2]
            other_end = other[4] or other[3]
            other_amount = other[1]

            # Was 'other' open at the time 'bet' was placed?
            if other_placed <= bet_placed:
                if other_end is None or other_end >= bet_placed:
                    concurrent += 1
                    concurrent_amount += other_amount

        exposure_snapshots.append((bet_placed, concurrent, concurrent_amount))

        if i < 10 or i % 200 == 0:
            print(
                f"  At {bet_placed}: {concurrent} concurrent bets, ${concurrent_amount:,.2f} exposure"
            )

    # Find max concurrent
    max_exp = max(exposure_snapshots, key=lambda x: x[2])
    print(
        f"\n  MAX concurrent exposure: {max_exp[1]} bets, ${max_exp[2]:,.2f} at {max_exp[0]}"
    )

    # Distribution
    exp_amounts = [e[2] for e in exposure_snapshots]
    print(f"  Avg concurrent exposure: ${sum(exp_amounts) / len(exp_amounts):,.2f}")
    print(
        f"  Bets where exposure > $2,500 (25% of $10K): {sum(1 for e in exp_amounts if e > 2500)}"
    )
    print(
        f"  Bets where exposure > $5,000 (50% of $10K): {sum(1 for e in exp_amounts if e > 5000)}"
    )
    print(
        f"  Bets where exposure > $10,000 (100% of $10K): {sum(1 for e in exp_amounts if e > 10000)}"
    )

# 4. Check for order_ids and tx_hashes (real vs paper)
print("\n--- REAL vs PAPER TRADES ---")
c.execute("SELECT COUNT(*) FROM bets WHERE order_id IS NOT NULL AND order_id != ''")
has_order = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE tx_hash IS NOT NULL AND tx_hash != ''")
has_tx = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets")
total = c.fetchone()[0]
print(f"  Total bets: {total}")
print(f"  With order_id: {has_order} ({100 * has_order / total:.0f}%)")
print(f"  With tx_hash: {has_tx} ({100 * has_tx / total:.0f}%)")

# Check sample order_ids
c.execute(
    "SELECT id, order_id, tx_hash, market_id, amount FROM bets WHERE order_id IS NOT NULL LIMIT 5"
)
for r in c.fetchall():
    print(f"  ID={r[0]}, order_id={r[1]}, tx={r[2]}, market={r[3]}, amt=${r[4]:.2f}")

# 5. Check if bets are paper mode
print("\n--- PAPER MODE CHECK ---")
try:
    c.execute("SELECT * FROM paper_trades LIMIT 5")
    print(f"  paper_trades table exists with data: {[r for r in c.fetchall()]}")
except Exception:
    print("  No paper_trades table")

# 6. How many bets can be open simultaneously in the first hour of Jun 16?
print("\n--- FIRST HOUR OF JUN 16: BET PLACEMENT RATE ---")
c.execute("""
    SELECT id, amount, placed_at, settled_at, closed_at
    FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY placed_at
    LIMIT 100
""")
first100 = c.fetchall()
for r in first100[:20]:
    print(f"  ID={r[0]}, amt=${r[1]:.2f}, placed={r[2]}, settled={r[3]}, closed={r[4]}")

# 7. Check portfolio growth timeline
print("\n--- PORTFOLIO BALANCE OVER TIME ---")
c.execute("SELECT * FROM portfolio ORDER BY last_updated")
for r in c.fetchall():
    print(f"  {r}")

# 8. Critical: check exposure cap logic
print("\n--- EXPOSURE CAP CONFIG ---")
c.execute("""
    SELECT DISTINCT market_id FROM bets 
    WHERE DATE(placed_at) = '2026-06-16'
    ORDER BY market_id
""")
markets = [r[0] for r in c.fetchall()]
print(f"  Unique markets on Jun 16: {len(markets)}")
for m in markets[:10]:
    c.execute(
        "SELECT COUNT(*), SUM(amount) FROM bets WHERE market_id=? AND DATE(placed_at)='2026-06-16'",
        (m,),
    )
    cnt, amt = c.fetchone()
    print(f"    {m}: {cnt} bets, ${amt:.2f}")

# 9. How many bets per unique market?
print("\n--- BETS PER MARKET (Jun 16) ---")
c.execute("""
    SELECT market_id, COUNT(*) as cnt, SUM(amount) as total_amt,
           MIN(entry_price) as min_entry, MAX(entry_price) as max_entry
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    GROUP BY market_id
    ORDER BY cnt DESC
    LIMIT 15
""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} bets, ${r[2]:.2f}, entry range: {r[3]:.4f} - {r[4]:.4f}")

# 10. City diversity on Jun 16
print("\n--- CITIES ON JUN 16 ---")
c.execute("""
    SELECT city, COUNT(*) as cnt, SUM(amount) as total
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    GROUP BY city ORDER BY cnt DESC
""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} bets, ${r[2]:.2f}")

# 11. Check the max_bet_amount and how it relates to $30
print("\n--- BET SIZE DISTRIBUTION ---")
c.execute("""
    SELECT 
        CASE 
            WHEN amount < 5 THEN '$0-5'
            WHEN amount < 10 THEN '$5-10'
            WHEN amount < 15 THEN '$10-15'
            WHEN amount < 20 THEN '$15-20'
            WHEN amount < 25 THEN '$20-25'
            WHEN amount < 30 THEN '$25-30'
            WHEN amount >= 30 THEN '$30+'
        END as bracket,
        COUNT(*) as cnt,
        SUM(amount) as total
    FROM bets
    GROUP BY bracket
    ORDER BY MIN(amount)
""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} bets, ${r[2]:,.2f}")

conn.close()
print("\nDONE.")
