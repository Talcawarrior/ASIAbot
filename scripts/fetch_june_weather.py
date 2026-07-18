import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.polymarket_ingest import PolymarketIngest

# Fetch closed weather markets
ingest = PolymarketIngest()

# Fetch closed weather markets
df = ingest.fetch_closed_markets(
    category="Weather", end_date_min="2026-06-01", end_date_max="2026-06-30", limit=500, use_cache=False
)

print(f"Total weather markets in June 2026: {len(df)}")
if not df.empty:
    # Save to CSV instead of printing
    df[["id", "question", "endDate", "closedTime", "yes_price", "no_price", "resolved_outcome"]].to_csv(
        "june_2026_weather_markets.csv", index=False, encoding="utf-8"
    )
    print("Saved to june_2026_weather_markets.csv")
    print(f"Columns: {list(df.columns)}")
    print(f"Sample: {df[['id', 'question', 'endDate', 'resolved_outcome']].head(10).to_string()}")
else:
    print("No weather markets found in June 2026")
