import requests

# Polymarket Gamma API - fetch closed markets
url = "https://gamma-api.polymarket.com/markets"
params = {"closed": "true", "limit": 500, "active": "false"}

response = requests.get(url, params=params)
markets = response.json()

# Filter for weather/temperature markets closed around June 1
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
        end_date = m.get("endDate", "")
        closed_time = m.get("closedTime", "")
        if "2026-06-01" in end_date or "2026-06-01" in closed_time:
            weather_markets.append(m)

print(f"Found {len(weather_markets)} weather markets closed around June 1")
for m in weather_markets:
    print(f"ID: {m['id']}")
    print(f"Question: {m['question']}")
    print(f"EndDate: {m.get('endDate')}")
    print(f"ClosedTime: {m.get('closedTime')}")
    print(f"Resolved: {m.get('resolved')}")
    print(f"ResolvedOutcome: {m.get('resolvedOutcome')}")
    print(f"YesPrice: {m.get('yesPrice')}")
    print(f"NoPrice: {m.get('noPrice')}")
    print("---")
