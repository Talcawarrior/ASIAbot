import sqlite3
import json

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Check how many rows have raw_data
c.execute('SELECT COUNT(*) FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != ""')
print(f"Rows with raw_data: {c.fetchone()[0]}")

# Check how many have clob_token_ids already
c.execute('SELECT COUNT(*) FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != ""')
print(f"Rows with clob_token_ids: {c.fetchone()[0]}")

# Try the migration query
c.execute('SELECT id, raw_data FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != "" LIMIT 1')
r = c.fetchone()
if r:
    raw = json.loads(r[1])
    clob_token_ids = raw.get("clobTokenIds", [])
    print(f"clobTokenIds: {clob_token_ids}")
    print(f"is list: {isinstance(clob_token_ids, list)}")
    print(f"len: {len(clob_token_ids)}")

conn.close()
