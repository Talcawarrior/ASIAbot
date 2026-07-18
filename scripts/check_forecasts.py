import pandas as pd

df = pd.read_parquet('data/unified/forecasts.parquet')
print(f'Forecasts: {len(df)} rows')
print(f'Date range: {df["target_date"].min()} to {df["target_date"].max()}')
print(f'Cities: {df["city"].nunique()}')
print(f'Models: {df["model"].nunique()}')
print(df.head())