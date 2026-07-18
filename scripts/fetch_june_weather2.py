import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.polymarket_ingest import PolymarketIngest

# Fetch all closed markets
ingest = PolymarketIngest()

df = ingest.fetch_closed_markets(end_date_min="2026-06-01", end_date_max="2026-06-30", limit=500, use_cache=False)

print(f"Total markets in June 2026: {len(df)}")

# Filter for actual weather/temperature markets
weather_keywords = [
    "temperature",
    "temp",
    "weather",
    "highest",
    "lowest",
    "high temp",
    "low temp",
    "celsius",
    "fahrenheit",
    "precipitation",
    "rain",
    "snow",
]
weather_df = df[df["question"].str.lower().str.contains("|".join(weather_keywords), na=False)]

print(f"Actual weather/temperature markets: {len(weather_df)}")

if not weather_df.empty:
    weather_df[["id", "question", "endDate", "closedTime", "yes_price", "no_price", "resolved_outcome"]].to_csv(
        "june_2026_weather_markets.csv", index=False, encoding="utf-8"
    )
    print("Saved to june_2026_weather_markets.csv")
    print(weather_df[["id", "question", "endDate", "resolved_outcome"]].head(20).to_string())
else:
    print("No weather markets found")
