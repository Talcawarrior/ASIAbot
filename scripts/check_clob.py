import sqlite3
conn = sqlite3.connect('data/bot.db')
c = conn.cursor()

# Check if clob_token_ids column exists and has data
c.execute('SELECT id, city, clob_token_ids FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != "" LIMIT 5')
for r in c.fetchall():
    print(f'id={r[0]}, city={r[1]}, clob_token_ids={r[2][:200]}...')

# Count
c.execute('SELECT COUNT(*) FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != ""')
print(f'Total with clob_token_ids: {c.fetchone()[0]}')

conn.close()