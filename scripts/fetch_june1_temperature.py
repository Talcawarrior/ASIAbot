import requests
import json
import time
from typing import List, Dict, Optional

GAMMA_BASE = "https://gamma-api.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def get_city_list() -> List[str]:
    """Step 1: Get city list from daily-temperature page"""
    url = "https://polymarket.com/predictions/daily-temperature"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})

    # Parse the page for city names
    # The page likely has links to event pages
    import re

    cities = re.findall(r"/event/highest-temperature-in-([^/?]+)", response.text)
    # Clean up city names
    cities = [c.replace("-", " ").title() for c in cities]
    return list(set(cities))


def check_event_exists(city: str) -> Optional[str]:
    """Step 2: Check if event exists for city on June 1, 2026"""
    slug = f"highest-temperature-in-{city.lower().replace(' ', '-')}-on-june-1-2026"
    url = f"https://polymarket.com/event/{slug}"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)

    if "Highest temperature in" in response.text:
        return slug
    return None


def get_event_id(slug: str) -> Optional[str]:
    """Step 3: Get event ID from Gamma API"""
    url = f"{GAMMA_BASE}/events"
    params = {"slug": slug}
    response = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug})
    if response.status_code == 200:
        events = response.json()
        if events:
            return events[0].get("id")
    return None


def get_winner(event_id: str) -> Optional[Dict]:
    """Step 4: Get market outcomes from event"""
    url = f"{GAMMA_BASE}/events/{event_id}"
    response = requests.get(url)
    if response.status_code == 200:
        event = response.json()
        markets = event.get("markets", [])
        for market in markets:
            outcome_prices = market.get("outcomePrices", [])
            if outcome_prices == ["1", "0"]:
                return {
                    "market_id": market.get("id"),
                    "question": market.get("question"),
                    "winner": "Yes",
                    "outcome_prices": outcome_prices,
                }
            elif outcome_prices == ["0", "1"]:
                return {
                    "market_id": market.get("id"),
                    "question": market.get("question"),
                    "winner": "No",
                    "outcome_prices": outcome_prices,
                }
    return None


def main():
    print("=== Step 1: Getting city list ===")
    cities = get_city_list()
    print(f"Found {len(cities)} cities: {cities[:10]}...")

    results = []
    for city in cities:
        print(f"\nChecking {city}...")
        slug = check_event_exists(city)
        if not slug:
            print(f"  No event found for {city}")
            continue

        print(f"  Event slug: {slug}")
        event_id = get_event_id(slug)
        if not event_id:
            print("  No event ID found")
            continue

        print(f"  Event ID: {event_id}")
        winner = get_winner(event_id)
        if winner:
            print(f"  Winner: {winner['winner']} - {winner['question']}")
            results.append({"city": city, "slug": slug, "event_id": event_id, **winner})
        else:
            print("  No winner found")

        time.sleep(0.5)  # Be polite

    print(f"\n=== Results: {len(results)} markets ===")
    for r in results:
        print(f"  {r['city']}: {r['winner']} - {r['question']}")

    # Save results
    with open("june1_2026_temperature_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved to june1_2026_temperature_results.json")


if __name__ == "__main__":
    main()
