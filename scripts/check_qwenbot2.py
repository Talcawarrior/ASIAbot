import sqlite3

conn = sqlite3.connect(r'C:\Users\fdemir\Documents\New project\QwenBot\data\bot.db')
c = conn.cursor()

# Check tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in c.fetchall():
    print(r[0])

# Check each table
for table in ['weather_markets', 'weather_forecasts', 'analyses', 'bets', 'portfolio', 'model_performance']:
    try:
        c.execute(f'SELECT COUNT(*) FROM {table}')
        count = c.fetchone()[0]
        print(f'{table}: {count} rows')
    except Exception as e:
        print(f'{table}: ERROR - {e}')

# Check date ranges
for table, date_col in [('weather_markets', 'target_date'), ('weather_forecasts', 'target_date'), ('analyses', 'analyzed_at'), ('bets', 'placed_at')]:
    try:
        c.execute(f'SELECT MIN({date_col}), MAX({date_col}) FROM {table} WHERE {date_col} IS NOT NULL')
        r = c.fetchone()
        print(f'{table}.{date_col}: {r[0]} to {r[1]}')
    except Exception as e:
        print(f'{table}.{date_col}: ERROR - {e}')

conn.close()