"""Fetch active Polymarket weather markets and add to brier_df."""

import logging
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data_pipeline.polymarket_ingest import PolymarketIngest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("POLY_FETCH")

# City name normalization
CITY_ALIASES = {
    "new york city": "New York",
    "nyc": "New York",
    "new york": "New York",
    "london": "London",
    "tokyo": "Tokyo",
    "seoul": "Seoul",
    "sydney": "Sydney",
    "dubai": "Dubai",
    "paris": "Paris",
    "beijing": "Beijing",
    "shanghai": "Shanghai",
    "hong kong": "Hong Kong",
    "singapore": "Singapore",
    "taipei": "Taipei",
    "mumbai": "Mumbai",
    "delhi": "Delhi",
    "manila": "Manila",
    "toronto": "Toronto",
    "wellington": "Wellington",
    "melbourne": "Melbourne",
    "bangkok": "Bangkok",
    "jakarta": "Jakarta",
    "istanbul": "Istanbul",
    "moscow": "Moscow",
    "berlin": "Berlin",
    "madrid": "Madrid",
    "rome": "Rome",
    "mexico city": "Mexico City",
    "buenos aires": "Buenos Aires",
    "sao paulo": "São Paulo",
    "são paulo": "São Paulo",
    "rio de janeiro": "Rio de Janeiro",
    "cairo": "Cairo",
    "lagos": "Lagos",
    "nairobi": "Nairobi",
    "cape town": "Cape Town",
    "amsterdam": "Amsterdam",
    "brussels": "Brussels",
    "zurich": "Zurich",
    "munich": "Munich",
    "vienna": "Vienna",
    "prague": "Prague",
    "warsaw": "Warsaw",
    "budapest": "Budapest",
    "helsinki": "Helsinki",
    "oslo": "Oslo",
    "stockholm": "Stockholm",
    "copenhagen": "Copenhagen",
    "dublin": "Dublin",
    "lisbon": "Lisbon",
    "athens": "Athens",
    "tel aviv": "Tel Aviv",
    "doha": "Doha",
    "abu dhabi": "Abu Dhabi",
    "riyadh": "Riyadh",
    "jeddah": "Jeddah",
    "karachi": "Karachi",
    "lahore": "Lahore",
    "dhaka": "Dhaka",
    "ho chi minh city": "Ho Chi Minh City",
    "hanoi": "Hanoi",
    "kuala lumpur": "Kuala Lumpur",
    "singapore": "Singapore",
    "guangzhou": "Guangzhou",
    "shenzhen": "Shenzhen",
    "chengdu": "Chengdu",
    "chongqing": "Chongqing",
    "qingdao": "Qingdao",
    "wuhan": "Wuhan",
    "hangzhou": "Hangzhou",
    "nanjing": "Nanjing",
    "suzhou": "Suzhou",
    "busan": "Busan",
    "osaka": "Osaka",
    "fukuoka": "Fukuoka",
    "sapporo": "Sapporo",
    "bangalore": "Bangalore",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "hyderabad": "Hyderabad",
    "ahmedabad": "Ahmedabad",
    "lucknow": "Lucknow",
    "ankara": "Ankara",
    "chicago": "Chicago",
    "los angeles": "Los Angeles",
    "san francisco": "San Francisco",
    "seattle": "Seattle",
    "dallas": "Dallas",
    "houston": "Houston",
    "atlanta": "Atlanta",
    "miami": "Miami",
    "denver": "Denver",
}


def extract_city_from_question(question: str) -> str | None:
    """Extract city name from Polymarket question text."""
    q = question.lower()

    # Match patterns like "Will the high temperature in New York be above 80°F?"
    patterns = [
        r"(?:high|low|temperature)\s+(?:in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:high|low|temperature)",
    ]

    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            city_raw = match.group(1).strip()
            city_lower = city_raw.lower()
            if city_lower in CITY_ALIASES:
                return CITY_ALIASES[city_lower]
            return city_raw

    return None


def extract_threshold_from_question(question: str) -> tuple[float | None, str | None]:
    """Extract temperature threshold and unit from question."""
    # Match patterns like "80°F", "80°F", "above 80", "below 30°C"
    patterns = [
        r"(\d+(?:\.\d+)?)\s*°?\s*([fFcC])",
        r"(?:above|below|over|under)\s+(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).upper() if match.lastindex >= 2 else None
            return value, unit

    return None, None


def extract_market_type(question: str) -> str | None:
    """Extract market type (HIGH/LOW) from question."""
    q = question.lower()
    if "high" in q or "above" in q or "over" in q:
        return "HIGH"
    if "low" in q or "below" in q or "under" in q:
        return "LOW"
    return None


def run():
    """Fetch active weather markets and print results."""
    ingest = PolymarketIngest()

    logger.info("Fetching active markets...")
    active = ingest.fetch_active_markets(limit=200)
    logger.info("Fetched %d active markets", len(active))

    if active.empty:
        logger.warning("No active markets found")
        return

    # Filter for weather markets
    weather_keywords = [
        "temperature",
        "high temp",
        "low temp",
        "°f",
        "°c",
        "fahrenheit",
        "celsius",
        "weather",
        "rain",
        "snow",
    ]

    def is_weather(row):
        q = str(row.get("question", "")).lower()
        return any(kw in q for kw in weather_keywords)

    weather = active[active.apply(is_weather, axis=1)]
    logger.info("Weather markets: %d", len(weather))

    if weather.empty:
        logger.warning("No weather markets found")
        return

    # Extract structured data
    results = []
    for _, row in weather.iterrows():
        question = row.get("question", "")
        city = extract_city_from_question(question)
        threshold, unit = extract_threshold_from_question(question)
        market_type = extract_market_type(question)

        if city and threshold is not None:
            # Convert Fahrenheit to Celsius if needed
            if unit and unit.upper() == "F":
                threshold_c = (threshold - 32.0) * 5.0 / 9.0
            else:
                threshold_c = threshold

            # Get current price
            outcomes = row.get("outcomePrices", "")
            yes_price = None
            if outcomes:
                try:
                    import json

                    prices = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                    if isinstance(prices, list) and len(prices) >= 1:
                        yes_price = float(prices[0])
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass

            results.append(
                {
                    "market_id": str(row.get("id", "")),
                    "question": question,
                    "city": city,
                    "threshold": round(threshold_c, 1),
                    "market_type": market_type,
                    "yes_price": yes_price,
                    "volume": row.get("volume", 0),
                }
            )

    df = pd.DataFrame(results)
    logger.info("Extracted %d weather markets with structured data", len(df))

    if not df.empty:
        print("\n=== Active Weather Markets ===")
        print(df[["city", "threshold", "market_type", "yes_price", "question"]].to_string(index=False))

        # Save to CSV for reference
        os.makedirs("data", exist_ok=True)
        df.to_csv("data/active_weather_markets.csv", index=False)
        logger.info("Saved to data/active_weather_markets.csv")


if __name__ == "__main__":
    run()
