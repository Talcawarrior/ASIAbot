import sqlite3

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

# Check historical_calibrations
c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM historical_calibrations")
r = c.fetchone()
print(f"Calibrations: {r[0]} to {r[1]}, {r[2]} rows")

# Check analyses
c.execute("SELECT MIN(analyzed_at), MAX(analyzed_at), COUNT(*) FROM analyses WHERE analyzed_at IS NOT NULL")
r = c.fetchone()
print(f"Analyses: {r[0]} to {r[1]}, {r[2]} rows")

# Check bets
c.execute("SELECT MIN(placed_at), MAX(placed_at), COUNT(*) FROM bets WHERE placed_at IS NOT NULL")
r = c.fetchone()
print(f"Bets: {r[0]} to {r[1]}, {r[2]} rows")

# Check weather_markets
c.execute("SELECT MIN(target_date), MAX(target_date), COUNT(*) FROM weather_markets WHERE target_date IS NOT NULL")
r = c.fetchone()
print(f"Markets: {r[0]} to {r[1]}, {r[2]} rows")

# Check settled markets
c.execute(
    'SELECT MIN(target_date), MAX(target_date), COUNT(*) FROM weather_markets WHERE status IN ("settled_win","settled_loss")'
)
r = c.fetchone()
print(f"Settled Markets: {r[0]} to {r[1]}, {r[2]} rows")

conn.close()
