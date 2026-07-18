import pandas as pd

df = pd.read_parquet('data/unified/actuals.parquet')
print(f'Actuals: {len(df)} rows')
print(f'Date range: {df["date"].min()} to {df["date"].max()}')
print(f'Cities: {df["city"].nunique()}')
print(df.head())