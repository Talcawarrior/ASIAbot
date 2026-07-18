import sqlite3
conn = sqlite3.connect('data/bot.db')
c = conn.cursor()

# Total analyses
c.execute('SELECT COUNT(*) FROM analyses')
print(f'Total analyses: {c.fetchone()[0]}')

# Analyses with should_bet=True
c.execute('SELECT COUNT(*) FROM analyses WHERE should_bet = 1')
print(f'Analyses with should_bet=True: {c.fetchone()[0]}')

# Analyses with should_bet=False and reasons
c.execute('SELECT reason, COUNT(*) FROM analyses WHERE should_bet = 0 GROUP BY reason')
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')

# Bets placed
c.execute('SELECT COUNT(*) FROM bets WHERE status IN ("placed","won","lost","closed_early")')
print(f'Bets placed/settled: {c.fetchone()[0]}')

# Bets rejected/cancelled
c.execute('SELECT status, COUNT(*) FROM bets GROUP BY status')
for r in c.fetchall():
    print(f'  Bet {r[0]}: {r[1]}')

conn.close()