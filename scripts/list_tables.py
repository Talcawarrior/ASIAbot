import sqlite3

c = sqlite3.connect("data/bot.db")
tables = [
    r[0]
    for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
]
for t in sorted(tables):
    print(t)
