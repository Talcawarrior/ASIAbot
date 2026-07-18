import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_pipeline.polymarket_ingest import PolymarketIngest

# Fetch all closed markets for June 2026
ingest = PolymarketIngest()

df = ingest.fetch_closed_markets(
    end_date_min="2026-06-01",
    end_date_max="2026-06-30",
    limit=500,
    use_cache=False
)

print(f"Total markets in June 2026: {len(df)}")

# Filter for temperature markets specifically
temp_keywords = ['temperature', 'temp', 'highest', 'lowest', 'high temp', 'low temp', 'celsius', 'fahrenheit', 'degree']
temp_df = df[df['question'].str.lower().str.contains('|'.join(temp_keywords), na=False)]

print(f"Actual temperature markets: {len(temp_df)}")

if not temp_df.empty:
    temp_df[['id', 'question', 'endDate', 'closedTime', 'yes_price', 'no_price', 'resolved_outcome']].to_csv('june_2026_temp_markets.csv', index=False, encoding='utf-8')
    print("Saved to june_2026_temp_markets.csv")
    print(temp_df[['id', 'question', 'endDate', 'resolved_outcome']].to_string())
else:
    print("No temperature markets found")

# Also check precipitation markets
precip_keywords = ['precipitation', 'rain', 'snow', 'mm of', 'inches of']
precip_df = df[df['question'].str.lower().str.contains('|'.join(precip_keywords), na=False)]
print(f"\nPrecipitation markets: {len(precip_df)}")
if not precip_df.empty:
    print(precip_df[['id', 'question', 'endDate', 'resolved_outcome']].to_string())