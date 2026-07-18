import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()
c.execute(
    'SELECT id, question, city, city_code, metric, threshold, market_type, yes_price, no_price, status, target_date FROM weather_markets WHERE status IN ("settled_win","settled_loss","expired") LIMIT 10'
)
for r in c.fetchall():
    print(
        f"id={r[0]}, city={r[2]}, metric={r[4]}, thresh={r[5]}, type={r[6]}, yes={r[7]}, no={r[8]}, status={r[9]}, target={r[10]}"
    )
    print(f"  Q: {r[1][:80]}...")
print()
c.execute("SELECT status, COUNT(*) FROM weather_markets GROUP BY status")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")
conn.close()
