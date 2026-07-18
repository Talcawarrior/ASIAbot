import sqlite3
import json

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Check raw stored value
c.execute(
    'SELECT id, city, clob_token_ids FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != "" LIMIT 1'
)
r = c.fetchone()
print(f"id={r[0]}, city={r[1]}")
print(f"raw clob_token_ids: {r[2][:300]}")
print(f"type: {type(r[2])}")

# Try to parse
try:
    parsed = json.loads(r[2])
    print(f"parsed: {parsed[:2]}")
    print(f"parsed type: {type(parsed)}")
except Exception as e:
    print(f"parse error: {e}")

conn.close()
