import sqlite3
import json

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()
c.execute('SELECT id, raw_data FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != "" LIMIT 3')
for r in c.fetchall():
    print(f"id={r[0]}")
    try:
        raw = json.loads(r[1])
        print(f"  keys: {list(raw.keys())}")
        if "tokens" in raw:
            print(f"  tokens: {raw['tokens'][:2]}")
        if "clobTokenIds" in raw:
            print(f"  clobTokenIds: {raw['clobTokenIds']}")
    except Exception as e:
        print(f"  error: {e}")
    print()
conn.close()
