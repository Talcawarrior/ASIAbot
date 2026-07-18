"""Debug: check full calibration data coverage."""

import sqlite3
import pandas as pd

conn = sqlite3.connect("data/bot.db")
cal = pd.read_sql("SELECT city, date, model, predicted_value FROM historical_calibrations", conn)
conn.close()

print(f"Total rows: {len(cal)}")
print(f"Cities ({cal['city'].nunique()}): {sorted(cal['city'].unique())}")
print(f"Dates ({cal['date'].nunique()}): {sorted(cal['date'].unique())[:5]}...")
print(f"Models ({cal['model'].nunique()}): {sorted(cal['model'].unique())}")
print()

# Check which cities overlap with brier_df
from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier_cities = set(brier["city"].unique())
cal_cities = set(cal["city"].unique())
print(f"Brier cities: {len(brier_cities)}")
print(f"Cal cities: {len(cal_cities)}")
print(f"Overlap: {len(brier_cities & cal_cities)}")
missing = brier_cities - cal_cities
if missing:
    print(f"Missing from cal: {missing}")

# Check date coverage
cal["date_only"] = pd.to_datetime(cal["date"], format="mixed").dt.date.astype(str)
brier["date_only"] = pd.to_datetime(brier["target_date"], errors="coerce").dt.date.astype(str)
brier_dates = set(brier["date_only"].unique())
cal_dates = set(cal["date_only"].unique())
print(f"\nBrier dates: {sorted(brier_dates)}")
print(f"Cal dates: {sorted(cal_dates)}")
print(f"Overlap: {sorted(brier_dates & cal_dates)}")
