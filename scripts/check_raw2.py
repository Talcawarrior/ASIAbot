import sqlite3, json
conn = sqlite3.connect('data/bot.db')
c = conn.cursor()
c.execute('SELECT id, raw_data FROM weather_markets WHERE raw_data IS NOT NULL AND raw_data != "" LIMIT 1')
r = c.fetchone()
if r:
    raw = json.loads(r[1])
    print(f'Keys: {list(raw.keys())}')
    print(f'clobTokenIds: {raw.get("clobTokenIds")}')
    print(f'conditionId: {raw.get("conditionId")}')
    print(f'tokens: {raw.get("tokens")}')
conn.close()