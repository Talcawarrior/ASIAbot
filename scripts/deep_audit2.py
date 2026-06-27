#!/usr/bin/env python3
"""CRITICAL: Are Jun 16 bets a bulk import or live trades?"""

import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# 1. All Jun 16 bets: timestamps — are they all at the same second?
print("=" * 70)
print("JUN 16 BET TIMESTAMPS — ARE THEY BULK INSERTED?")
print("=" * 70)
c.execute("""
    SELECT placed_at, COUNT(*) as cnt, MIN(id) as min_id, MAX(id) as max_id
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    GROUP BY placed_at
    ORDER BY cnt DESC
    LIMIT 20
""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} bets (IDs {r[2]}-{r[3]})")

# 2. How many UNIQUE seconds on Jun 16?
c.execute("""
    SELECT COUNT(DISTINCT placed_at) FROM bets WHERE DATE(placed_at) = '2026-06-16'
""")
unique_ts = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE DATE(placed_at) = '2026-06-16'")
total = c.fetchone()[0]
print(f"\n  {total} bets across {unique_ts} unique timestamps")
print(f"  That's {total / unique_ts:.0f} bets per timestamp on average")

# 3. First timestamp and last timestamp
c.execute("""
    SELECT MIN(placed_at), MAX(placed_at) FROM bets WHERE DATE(placed_at) = '2026-06-16'
""")
first, last = c.fetchone()
print(f"  First: {first}")
print(f"  Last:  {last}")

# 4. Spread across day?
c.execute("""
    SELECT strftime('%H', placed_at) as hour, COUNT(*) as cnt
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    GROUP BY hour ORDER BY hour
""")
print("\n  Hour distribution:")
for r in c.fetchall():
    bar = "#" * min(r[1] // 10, 50)
    print(f"    {r[0]}:00 -> {r[1]:5d} bets {bar}")

# 5. Check ALL days for bulk insert patterns
print("\n" + "=" * 70)
print("ALL DAYS: BETS PER UNIQUE TIMESTAMP")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day, 
           COUNT(*) as total,
           COUNT(DISTINCT placed_at) as unique_ts,
           ROUND(1.0 * COUNT(*) / COUNT(DISTINCT placed_at), 0) as bets_per_ts
    FROM bets
    GROUP BY day
    ORDER BY day
""")
for r in c.fetchall():
    flag = " ***BULK***" if r[3] > 50 else ""
    print(f"  {r[0]}: {r[1]:5d} bets, {r[2]:5d} timestamps, ~{int(r[3])} bets/ts{flag}")

# 6. City field is showing "30.0" — check what's in the city column
print("\n" + "=" * 70)
print("CITY FIELD AUDIT")
print("=" * 70)
c.execute("SELECT DISTINCT city FROM bets ORDER BY city LIMIT 30")
cities = [r[0] for r in c.fetchall()]
print(f"  Distinct city values: {cities}")
c.execute(
    "SELECT COUNT(*) FROM bets WHERE city = '30.0' OR city = '29.7' OR city = '30.0'"
)
num_amount_as_city = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets")
total = c.fetchone()[0]
print(f"  Bets where city looks like a dollar amount: {num_amount_as_city} / {total}")

# 7. Check the city_code column
print("\n--- city_code vs city ---")
try:
    c.execute(
        "SELECT DISTINCT city_code FROM bets WHERE city_code IS NOT NULL LIMIT 10"
    )
    city_codes = [r[0] for r in c.fetchall()]
    print(f"  city_code values: {city_codes}")
except Exception:
    print("  No city_code column or empty")

# 8. Check for an import script or seed data
print("\n" + "=" * 70)
print("FIRST 10 BET IDs: city field check")
print("=" * 70)
c.execute(
    "SELECT id, city, city_code, market_id, amount, stake_amount FROM bets ORDER BY id LIMIT 10"
)
for r in c.fetchall():
    print(
        f"  ID={r[0]}, city='{r[1]}', city_code='{r[2]}', market={r[3]}, amount=${r[4]:.2f}, stake=${r[5]:.2f}"
    )

# 9. CRITICAL: Check exposure at moment of each Jun 16 bet placement
# Were all 1447 bets placed in ONE batch (same second)?
print("\n" + "=" * 70)
print("CRITICAL: FIRST BATCH ANALYSIS")
print("=" * 70)
c.execute("""
    SELECT MIN(placed_at) FROM bets WHERE DATE(placed_at) = '2026-06-16'
""")
first_ts = c.fetchone()[0]
c.execute("""
    SELECT COUNT(*), SUM(amount) FROM bets 
    WHERE placed_at = (SELECT MIN(placed_at) FROM bets WHERE DATE(placed_at) = '2026-06-16')
""")
batch = c.fetchone()
print(f"  First timestamp: {first_ts}")
print(f"  Bets at that timestamp: {batch[0]}")
print(f"  Total amount: ${batch[1]:,.2f}")
print("  25% of $10,000: $2,500")
print(f"  Exposure / 25% limit: {batch[1] / 2500:.0f}x")

# 10. How many UNIQUE markets on Jun 16?
c.execute("""
    SELECT COUNT(DISTINCT market_id) FROM bets WHERE DATE(placed_at) = '2026-06-16'
""")
unique_markets = c.fetchone()[0]
print(f"\n  Unique markets: {unique_markets}")
print(f"  Avg bets per market: {total / unique_markets:.1f}")

# 11. Are bets on Jun 16 ALL on the same side?
print("\n--- SIDE DISTRIBUTION (Jun 16) ---")
c.execute("""
    SELECT side, COUNT(*), SUM(amount), AVG(entry_price) 
    FROM bets WHERE DATE(placed_at) = '2026-06-16'
    GROUP BY side
""")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} bets, ${r[2]:,.2f}, avg entry={r[3]:.4f}")

# 12. Total PnL by bet origin date
print("\n" + "=" * 70)
print("PROFIT ORIGIN: PnL BY PLACEMENT DATE")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day,
           COUNT(*) as bets,
           SUM(amount) as total_bet,
           SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
           SUM(pnl) as total_pnl,
           AVG(pnl) as avg_pnl,
           SUM(CASE WHEN settled_at IS NOT NULL OR closed_at IS NOT NULL THEN 1 ELSE 0 END) as closed
    FROM bets
    GROUP BY day ORDER BY day
""")
for r in c.fetchall():
    wr = f"{r[3] / r[6] * 100:.0f}%" if r[6] > 0 else "N/A"
    print(
        f"  {r[0]}: {r[1]:5d} bets, ${r[2]:>10,.2f} bet, {r[3]:4d}W/{r[4]:4d}L ({wr}), PnL=${r[5]:>10,.2f}, closed={r[6]}"
    )

# 13. Grand total verification
print("\n" + "=" * 70)
print("GRAND TOTAL VERIFICATION")
print("=" * 70)
c.execute(
    "SELECT COUNT(*), SUM(amount), SUM(pnl), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) FROM bets"
)
r = c.fetchone()
print(f"  Total bets: {r[0]}")
print(f"  Total amount: ${r[1]:,.2f}")
print(f"  Total PnL: ${r[2]:,.2f}")
print(f"  Wins: {r[3]}, Losses: {r[4]}")
print(f"  Win rate: {r[3] / (r[3] + r[4]) * 100:.1f}%")
print("  Portfolio: $10,000 → $136,281 (+$126,281)")
print(f"  PnL from bets: ${r[2]:,.2f}")

# 14. Were bets actually placed on Polymarket or just DB entries?
print("\n" + "=" * 70)
print("REAL vs SYNTHETIC: order_id / tx_hash analysis")
print("=" * 70)
c.execute("SELECT COUNT(*) FROM bets WHERE order_id IS NULL OR order_id = ''")
no_order = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE order_id IS NOT NULL AND order_id != ''")
has_order = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE tx_hash IS NULL OR tx_hash = ''")
no_tx = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets WHERE tx_hash IS NOT NULL AND tx_hash != ''")
has_tx = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM bets")
total = c.fetchone()[0]
print(f"  order_id: {has_order} have / {no_order} missing / {total} total")
print(f"  tx_hash:  {has_tx} have / {no_tx} missing / {total} total")

if has_order > 0:
    print("\n  Sample order_ids:")
    c.execute(
        "SELECT id, order_id, market_id, amount, placed_at FROM bets WHERE order_id IS NOT NULL AND order_id != '' LIMIT 10"
    )
    for r in c.fetchall():
        print(
            f"    ID={r[0]}, order={r[1]}, market={r[2]}, amt=${r[3]:.2f}, placed={r[4]}"
        )

# 15. Check bet amount patterns — are they ALL $30?
print("\n" + "=" * 70)
print("BET SIZE PATTERNS BY DATE")
print("=" * 70)
c.execute("""
    SELECT DATE(placed_at) as day,
           MIN(amount) as min_amt,
           MAX(amount) as max_amt,
           AVG(amount) as avg_amt,
           COUNT(DISTINCT ROUND(amount, 2)) as unique_sizes
    FROM bets
    GROUP BY day ORDER BY day
""")
for r in c.fetchall():
    print(
        f"  {r[0]}: min=${r[1]:.2f}, max=${r[2]:.2f}, avg=${r[3]:.2f}, {r[4]} unique sizes"
    )

conn.close()
print("\nDONE.")
