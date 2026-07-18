import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Add clob_token_ids column
try:
    c.execute("ALTER TABLE weather_markets ADD COLUMN clob_token_ids TEXT")
    print("Added clob_token_ids column")
except sqlite3.OperationalError as e:
    print(f"Column may already exist: {e}")

conn.commit()

# Now update with data from raw_data
c.execute('SELECT id, raw_data FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != ""')
rows = c.fetchall()
updated = 0
for row in rows:
    market_id, raw_data = row
    try:
        import json

        raw = json.loads(raw_data)
        tokens = raw.get("tokens", [])
        if tokens:
            c.execute("UPDATE weather_markets SET clob_token_ids = ? WHERE id = ?", (json.dumps(tokens), market_id))
            updated += 1
    except (json.JSONDecodeError, TypeError):
        pass

conn.commit()
print(f"Updated {updated} markets with clob_token_ids")

# Verify
c.execute('SELECT COUNT(*) FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != ""')
print(f"Total with clob_token_ids: {c.fetchone()[0]}")

# Show sample
c.execute(
    'SELECT id, city, clob_token_ids FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != "" LIMIT 3'
)
for r in c.fetchall():
    print(f"id={r[0]}, city={r[1]}, clob_token_ids={r[2][:200]}...")

conn.close()
