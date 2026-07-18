import sqlite3

conn = sqlite3.connect(r"C:\Users\fdemir\Documents\New project\QwenBot\data\bot.db")
c = conn.cursor()

# Check tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for r in c.fetchall():
    print(r[0])

# Check calibrations date range
c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM historical_calibrations")
r = c.fetchone()
print(f"Calibrations: {r[0]} to {r[1]}, {r[2]} rows")

# Check analyses date range
c.execute("SELECT MIN(analyzed_at), MAX(analyzed_at), COUNT(*) FROM analyses WHERE analyzed_at IS NOT NULL")
r = c.fetchone()
print(f"Analyses: {r[0]} to {r[1]}, {r[2]} rows")

# Check bets date range
c.execute("SELECT MIN(placed_at), MAX(placed_at), COUNT(*) FROM bets WHERE placed_at IS NOT NULL")
r = c.fetchone()
print(f"Bets: {r[0]} to {r[1]}, {r[2]} rows")

# Check markets date range
c.execute("SELECT MIN(target_date), MAX(target_date), COUNT(*) FROM weather_markets WHERE target_date IS NOT NULL")
r = c.fetchone()
print(f"Markets: {r[0]} to {r[1]}, {r[2]} rows")

conn.close()
