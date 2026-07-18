import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in c.fetchall():
    print(r[0])
conn.close()
