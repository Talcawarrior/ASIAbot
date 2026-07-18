import requests

# Polymarket Gamma API - fetch closed markets
url = "https://gamma-api.polymarket.com/markets"
params = {"closed": "true", "limit": 500, "active": "false"}

response = requests.get(url, params=params)
markets = response.json()

print(f"Total closed markets: {len(markets)}")

# Filter for weather/temperature markets
weather_markets = []
for m in markets:
    question = m.get("question", "").lower()
    if any(
        kw in question
        for kw in [
            "temperature",
            "temp",
            "weather",
            "highest",
            "lowest",
            "high temp",
            "low temp",
            "celsius",
            "fahrenheit",
        ]
    ):
        weather_markets.append(m)

print(f"Weather/temperature markets: {len(weather_markets)}")

# Show all their dates
for m in weather_markets:
    end_date = m.get("endDate", "")
    closed_time = m.get("closedTime", "")
    question = m.get("question", "")[:100]
    print(f"  ID: {m['id']} | End: {end_date} | Closed: {closed_time} | {question}...")
