import sqlite3
import json

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

c.execute('SELECT id, raw_data FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != ""')
rows = c.fetchall()
updated = 0
for row in rows:
    market_id, raw_data = row
    try:
        raw = json.loads(raw_data)
        clob_token_ids_str = raw.get("clobTokenIds", "[]")
        # Double parse: it's a JSON string inside the JSON
        clob_token_ids = json.loads(clob_token_ids_str)
        if clob_token_ids and isinstance(clob_token_ids, list):
            condition_id = raw.get("conditionId")
            tokens = []
            for i, token_id in enumerate(clob_token_ids):
                outcome = "YES" if i == 0 else "NO"
                tokens.append({"token_id": token_id, "outcome": outcome, "condition_id": condition_id})
            c.execute("UPDATE weather_markets SET clob_token_ids = ? WHERE id = ?", (json.dumps(tokens), market_id))
            updated += 1
    except (json.JSONDecodeError, TypeError):
        pass

conn.commit()
print(f"Updated {updated} markets with clob_token_ids")

# Verify
c.execute('SELECT COUNT(*) FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != ""')
print(f"Total with clob_token_ids: {c.fetchone()[0]}")

c.execute(
    'SELECT id, city, clob_token_ids FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != "" LIMIT 3'
)
for r in c.fetchall():
    parsed = json.loads(r[2])
    print(f"id={r[0]}, city={r[1]}, tokens={parsed}")

conn.close()
