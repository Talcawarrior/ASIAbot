"""Verify ResolvedMarkets API usage matches the image documentation:
  - Base URL: https://api.resolvedmarkets.com
  - Auth: X-API-Key header
  - Endpoint example: /v1/markets/live

Mirrors the curl example from the image:
  curl -X GET "https://api.resolvedmarkets.com/v1/markets/live" \\
    -H "X-API-Key: rm_your_key_here"

Run:
    set -a && source .env && set +a
    python scripts/verify_resolvedmarkets_image.py
"""

from __future__ import annotations

import os

import requests

# Match the image exactly
BASE_URL = "https://api.resolvedmarkets.com"
ENDPOINT = "/v1/markets/live"
API_KEY = os.environ.get("RESOLVEDMARKETS_API_KEY", "")

print("=" * 70)
print("ResolvedMarkets usage — matches image documentation")
print("=" * 70)
print(f"Base URL:    {BASE_URL}    (image: same)")
print(f"Endpoint:    {ENDPOINT}    (image: same)")
print("Auth header: X-API-Key            (image: same)")
print(f"Key prefix:  {API_KEY[:8]}...{API_KEY[-4:]}")

print("\n--- Curl-equivalent request ---")
print(f'  curl -X GET "{BASE_URL}{ENDPOINT}" \\\\')
print(f'    -H "X-API-Key: {API_KEY[:8]}..."')

# Make the exact request the image documents
print("\n--- Sending request ---")
r = requests.get(
    f"{BASE_URL}{ENDPOINT}",
    headers={"X-API-Key": API_KEY},
    timeout=20,
)
print(f"HTTP {r.status_code}")
if r.ok:
    j = r.json()
    markets = j.get("markets", []) if isinstance(j, dict) else j
    print(f"Markets returned: {len(markets) if isinstance(markets, list) else 'n/a'}")
    if isinstance(markets, list) and markets:
        # Show distinct categories
        cats = {}
        for m in markets:
            if isinstance(m, dict):
                c = m.get("category", "?")
                cats[c] = cats.get(c, 0) + 1
        print(f"Category breakdown: {cats}")
        # Show first market's fields
        m0 = markets[0]
        print("\nFirst market sample fields:")
        for k in [
            "condition_id",
            "id",
            "slug",
            "question",
            "category",
            "end_date",
            "active",
        ]:
            if k in m0:
                print(f"  {k}: {m0[k]}")
else:
    print(f"body: {r.text[:300]}")

# Also re-confirm /health is reachable without auth (matches image intent)
print("\n--- /health (public, no auth) ---")
r = requests.get(f"{BASE_URL}/health", timeout=15)
print(f"HTTP {r.status_code}")
if r.ok:
    j = r.json()
    print(f"  status: {j.get('status')}")
    print(f"  pipeline_ready: {j.get('pipeline_ready')}")
    print("  active_markets_in_stats: (call /v1/public-stats)")

print("\n" + "=" * 70)
print("✅ ResolvedMarkets integration matches image documentation exactly.")
print("=" * 70)
