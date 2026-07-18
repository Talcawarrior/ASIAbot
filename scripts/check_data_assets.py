"""Quick inventory of all data assets available for testing."""

import sqlite3
import os
import pandas as pd


def main():
    conn = sqlite3.connect("data/bot.db")

    # 1. historical_calibrations
    cal = pd.read_sql("SELECT * FROM historical_calibrations", conn)
    print(f"=== historical_calibrations: {len(cal)} rows ===")
    print(f"  cities({len(cal['city'].unique())}): {sorted(cal['city'].unique())}")
    print(f"  dates({len(cal['date'].unique())}): {sorted(cal['date'].unique())}")
    print(f"  models({len(cal['model'].unique())}): {sorted(cal['model'].unique())}")
    print(f"  columns: {list(cal.columns)}")
    print()

    # 2. analyses
    try:
        analyses = pd.read_sql("SELECT COUNT(*) as cnt FROM analyses", conn)
        print(f"=== analyses: {analyses['cnt'].iloc[0]} rows ===")
        # Check what we have
        sample = pd.read_sql("SELECT * FROM analyses LIMIT 3", conn)
        print(f"  columns: {list(sample.columns)}")
    except Exception as e:
        print(f"=== analyses: {e} ===")
    print()

    # 3. bets
    try:
        total = pd.read_sql("SELECT COUNT(*) as cnt FROM bets", conn)["cnt"].iloc[0]
        resolved = pd.read_sql("SELECT COUNT(*) as cnt FROM bets WHERE resolved=1", conn)["cnt"].iloc[0]
        wins = pd.read_sql("SELECT COUNT(*) as cnt FROM bets WHERE resolved=1 AND profit_usd > 0", conn)["cnt"].iloc[0]
        losses = pd.read_sql("SELECT COUNT(*) as cnt FROM bets WHERE resolved=1 AND profit_usd <= 0", conn)["cnt"].iloc[
            0
        ]
        print(f"=== bets: {total} total, {resolved} resolved ({wins}W/{losses}L) ===")
        # Open positions
        open_bets = pd.read_sql("SELECT COUNT(*) as cnt FROM bets WHERE resolved=0", conn)["cnt"].iloc[0]
        print(f"  open positions: {open_bets}")
    except Exception as e:
        print(f"=== bets: {e} ===")
    print()

    # 4. model performance
    try:
        mp = pd.read_sql("SELECT * FROM model_performance ORDER BY date DESC LIMIT 5", conn)
        print("=== model_performance ===")
        print(mp.to_string(index=False))
    except Exception as e:
        print(f"=== model_performance: {e} ===")
    print()

    # 5. Parquets
    for f in ["actuals.parquet", "forecasts.parquet"]:
        p = f"data/unified/{f}"
        if os.path.exists(p):
            df = pd.read_parquet(p)
            print(f"=== {f}: {len(df)} rows ===")
            print(f"  columns: {list(df.columns)}")
        else:
            print(f"=== {f}: DOES NOT EXIST ===")
    print()

    # 6. Brier dataset (the key one)
    print("=== brier_dataset (build_brier_dataset) ===")
    from data_pipeline.unified_datastore import UnifiedDatastore

    ds = UnifiedDatastore()
    brier = ds.build_brier_dataset()
    print(f"  rows: {len(brier)}")
    print(f"  yes_price range: [{brier['yes_price'].min():.4f}, {brier['yes_price'].max():.4f}]")
    print(f"  realized_yes: {dict(brier['realized_yes'].value_counts())}")

    conn.close()


if __name__ == "__main__":
    main()
