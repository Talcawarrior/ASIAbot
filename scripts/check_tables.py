import sqlite3
import os

conn = sqlite3.connect('data/bot.db')
c = conn.cursor()

# Check what tables exist
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in c.fetchall():
    print(r[0])

# Check actuals table
c.execute('SELECT name FROM sqlite_master WHERE type="table" AND name LIKE "%actual%"')
print('Actual tables:', c.fetchall())

# Check unified parquet files
for f in os.listdir('data/unified'):
    print(f'Unified: {f}')

conn.close()