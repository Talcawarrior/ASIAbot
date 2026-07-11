"""Migration: Add adjusted_edge column to analyses table."""

import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "data", "bot.db")

conn = sqlite3.connect(DB)
cursor = conn.cursor()

# Check if adjusted_edge already exists
cursor.execute("PRAGMA table_info(analyses)")
cols = [row[1] for row in cursor.fetchall()]
print(f"analyses columns: {cols}")

if "adjusted_edge" not in cols:
    print("Adding adjusted_edge column...")
    cursor.execute("ALTER TABLE analyses ADD COLUMN adjusted_edge REAL")
    conn.commit()
    print("DONE: adjusted_edge column added")
else:
    print("adjusted_edge already exists - skipping")

# Verify
cursor.execute("PRAGMA table_info(analyses)")
cols = [row[1] for row in cursor.fetchall()]
print(f"Updated analyses columns: {cols}")

# Also check if there's an rmse column we need in historical_calibrations
cursor.execute("PRAGMA table_info(historical_calibrations)")
hcols = [row[1] for row in cursor.fetchall()]
print(f"\nhistorical_calibrations columns: {hcols}")

conn.close()
print("\nMigration complete!")
