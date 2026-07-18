import pandas as pd

# Check actuals parquet
df = pd.read_parquet('data/unified/actuals.parquet')
print(f'Actuals: {len(df)} rows')
print(f'Date range: {df["date"].min()} to {df["date"].max()}')
print(f'Cities: {df["city"].nunique()}')
print(df.head())

# Check markets parquet
df = pd.read_parquet('data/unified/markets.parquet')
print(f'\nMarkets: {len(df)} rows')
print(f'Date range: {df["target_date"].min()} to {df["target_date"].max()}')
print(df.head())

# Check forecasts parquet
df = pd.read_parquet('data/unified/forecasts.parquet')
print(f'\nForecasts: {len(df)} rows')
print(f'Date range: {df["target_date"].min()} to {df["target_date"].max()}')
print(df.head())