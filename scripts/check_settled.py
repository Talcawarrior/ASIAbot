import sqlite3
conn = sqlite3.connect('data/bot.db')
c = conn.cursor()
c.execute('SELECT id, city, metric, threshold, market_type, yes_price, no_price, status, target_date FROM weather_markets WHERE status IN ("settled_win","settled_loss") LIMIT 20')
for r in c.fetchall():
    print(f'id={r[0]}, city={r[1]}, metric={r[2]}, thresh={r[3]}, type={r[4]}, yes={r[5]}, no={r[6]}, status={r[7]}, target={r[8]}')
conn.close()