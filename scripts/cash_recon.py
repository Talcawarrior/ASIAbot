#!/usr/bin/env python3
"""Cash reconciliation check."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
from database.models import OPEN_BET_STATUSES

conn = sqlite3.connect("data/bot.db")
c = conn.cursor()

c.execute("SELECT cash_balance, total_value, initial_value FROM portfolio WHERE id=1")
p = c.fetchone()
cash, total, initial = p[0], p[1], p[2]
print(f"Portfolio: cash={cash}, total_value={total}, initial={initial}")

closed_statuses = ("won", "lost", "settled", "closed_early")

c.execute(
    "SELECT COALESCE(SUM(amount), 0) FROM bets WHERE status IN "
    + str(OPEN_BET_STATUSES)
)
open_stakes = c.fetchone()[0]
print(f"Open bet stakes (locked in positions): {open_stakes}")

c.execute(
    "SELECT COALESCE(SUM(amount), 0) FROM bets WHERE status IN " + str(closed_statuses)
)
closed_stakes = c.fetchone()[0]
print(f"Closed bet stakes: {closed_stakes}")

# total_value should be cash + open_stakes (exposure)
expected_total = round(cash + open_stakes, 2)
print(
    f"\nExpected total_value = cash + open_exposure = {cash} + {open_stakes} = {expected_total}"
)
print(f"Actual total_value = {total}")
print(f"Gap = {round(total - expected_total, 2)}")

conn.close()
