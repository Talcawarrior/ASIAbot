"""Debug: why all prob_ cols are NaN after calibrations fallback."""

import sqlite3
import pandas as pd
from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier["join_date"] = pd.to_datetime(brier["target_date"], errors="coerce").dt.date.astype(str)

print("brier join_date sample:", brier["join_date"].unique())
print("brier city sample:", brier["city"].unique()[:5])
print()

# Read calibrations
db_path = ds.cfg.data_dir + "/../bot.db"
conn = sqlite3.connect(db_path)
cal = pd.read_sql("SELECT city, date, model, predicted_value FROM historical_calibrations LIMIT 10", conn)
conn.close()
print("calibrations sample:")
print(cal.head(5))
print()
print("cal date sample:", cal["date"].unique())
print()

# Check if the dates match
cal["join_date"] = pd.to_datetime(cal["date"], format="mixed").dt.date.astype(str)
print("cal join_date sample:", cal["join_date"].unique())

# Do the join
temp_pivot = cal.pivot_table(
    index=["city", "date"],
    columns="model",
    values="predicted_value",
    aggfunc="mean",
).reset_index()
temp_pivot["join_date"] = pd.to_datetime(temp_pivot["date"], format="mixed").dt.date.astype(str)

print("\ntemp_pivot join_date:", temp_pivot["join_date"].unique())
print("temp_pivot city:", temp_pivot["city"].unique())

# Check overlap
brier_cities = set(brier["city"].unique())
cal_cities = set(temp_pivot["city"].unique())
print(f"\nBrier cities: {len(brier_cities)}, Cal cities: {len(cal_cities)}")
print(f"Overlap: {len(brier_cities & cal_cities)}")
print(f"In brier but not cal: {brier_cities - cal_cities}")
print(f"In cal but not brier: {cal_cities - brier_cities}")

brier_dates = set(brier["join_date"].unique())
cal_dates = set(temp_pivot["join_date"].unique())
print(f"\nBrier dates: {brier_dates}")
print(f"Cal dates: {cal_dates}")
print(f"Overlap: {brier_dates & cal_dates}")
