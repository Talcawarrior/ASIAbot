import sqlite3
conn = sqlite3.connect('data/bot.db')
c = conn.cursor()

# 1 Hazirandan bu yana kapanmis/settle olmus marketler
c.execute("""
    SELECT status, COUNT(*), MIN(target_date), MAX(target_date)
    FROM weather_markets
    WHERE target_date >= "2026-06-01"
    AND status IN ("settled_win", "settled_loss", "resolved", "closed")
    GROUP BY status
""")
for r in c.fetchall():
    print(f'Status: {r[0]}, Count: {r[1]}, Min date: {r[2]}, Max date: {r[3]}')

# Toplam
c.execute("""
    SELECT COUNT(*) FROM weather_markets
    WHERE target_date >= "2026-06-01"
    AND status IN ("settled_win", "settled_loss", "resolved", "closed")
""")
print(f'Toplam (Jun 1+): {c.fetchone()[0]}')

# Tum zamanlar icin
c.execute("""
    SELECT status, COUNT(*) FROM weather_markets
    WHERE status IN ("settled_win", "settled_loss", "resolved", "closed")
    GROUP BY status
""")
print()
print('Tum zamanlar icin settled:')
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')

conn.close()