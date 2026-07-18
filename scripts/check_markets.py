import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Check weather_markets table
c.execute("""
    SELECT id, city, metric, threshold, market_type, target_date, yes_price, no_price, status
    FROM weather_markets
    WHERE status IN ('settled_win', 'settled_loss')
    ORDER BY target_date
""")
for r in c.fetchall():
    print(
        f"id={r[0]}, city={r[1]}, metric={r[2]}, thresh={r[3]}, type={r[4]}, target={r[5]}, yes={r[6]}, no={r[7]}, status={r[8]}"
    )

# Also check all markets
c.execute("SELECT status, COUNT(*) FROM weather_markets GROUP BY status")
print("\nMarket status counts:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

conn.close()
