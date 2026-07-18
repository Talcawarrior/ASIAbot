"""Debug _join_from_calibrations step by step."""

import os
import sqlite3
import pandas as pd
from data_pipeline.unified_datastore import UnifiedDatastore

# Simulate what _join_from_calibrations does
ds = UnifiedDatastore()

# 1. Build brier_df (what add_per_model_probabilities receives)
from asi_engine.karpathy_weekly import OPEN_METEO_API_TO_INTERNAL

brier = ds.build_brier_dataset()
brier["join_date"] = pd.to_datetime(brier["target_date"], errors="coerce").dt.date.astype(str)
print("brier join_date dtype:", brier["join_date"].dtype)
print("brier join_date sample:", brier["join_date"].head(3).tolist())

# 2. Read calibrations
db_path = os.path.join(ds.cfg.data_dir, "..", "bot.db")
conn = sqlite3.connect(db_path)
cal = pd.read_sql("SELECT city, date, model, predicted_value FROM historical_calibrations", conn)
conn.close()
cal["model_internal"] = cal["model"].map(lambda m: OPEN_METEO_API_TO_INTERNAL.get(m, m))

# 3. Pivot
temp_pivot = cal.pivot_table(
    index=["city", "date"],
    columns="model_internal",
    values="predicted_value",
    aggfunc="mean",
).reset_index()

temp_pivot["join_date"] = pd.to_datetime(temp_pivot["date"], format="mixed").dt.date.astype(str)
print("\ntemp_pivot join_date dtype:", temp_pivot["join_date"].dtype)
print("temp_pivot join_date sample:", temp_pivot["join_date"].head(3).tolist())
print("temp_pivot city sample:", temp_pivot["city"].head(3).tolist())

# 4. Merge
merged = brier.merge(temp_pivot, on=["city", "join_date"], how="left", suffixes=("", "_cal"))
print(f"\nAfter merge: {merged.shape}")
gfs_col = [c for c in merged.columns if "gfs" in c and c != "prob_gfs_seamless"]
print(f"gfs columns after merge: {gfs_col}")
if gfs_col:
    nn = merged[gfs_col[0]].notna().sum()
    print(f"  gfs non-null: {nn}/{len(merged)}")
else:
    print("  NO gfs column found!")
    # Check what columns the pivot created
    pivot_cols = [c for c in temp_pivot.columns if c not in ["city", "date", "join_date"]]
    print(f"  Pivot model columns: {pivot_cols}")
    brier_cols = list(brier.columns)
    print(f"  Brier columns: {brier_cols}")
    # Check for collisions
    overlap = set(pivot_cols) & set(brier_cols)
    if overlap:
        print(f"  COLUMN COLLISION: {overlap}")

# 5. If merge worked, test _to_prob_cal
if gfs_col and merged[gfs_col[0]].notna().any():
    row = merged[merged[gfs_col[0]].notna()].iloc[0]
    print("\nSample merged row:")
    print(f"  gfs_temp: {row[gfs_col[0]]}")
    print(f"  threshold: {row.get('threshold')}")
    print(f"  market_type: {row.get('market_type')}")
