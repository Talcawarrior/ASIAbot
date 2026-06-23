"""Try harder to find ResolvedMarkets coverage of our Polymarket weather markets:
  1) Pull /v1/markets/history?category=daily-temperature (their dedicated subcategory)
  2) For one of OUR slugs, try /v1/markets/by-slug/{slug} — maybe ResolvedMarkets
     uses a different conditionId for the same underlying market.

Run:
    set -a && source .env && set +a
    python scripts/probe_daily_temperature.py
"""

from __future__ import annotations

import os
import sys
import time

import requests

BASE = "https://api.resolvedmarkets.com"
API_KEY = os.environ.get("RESOLVEDMARKETS_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY}

# ---------------------------------------------------------------------------
# 1) Daily-temperature subcategory — full history
# ---------------------------------------------------------------------------

print("=" * 70)
print("1) /v1/markets/history?category=daily-temperature&limit=100")
print("=" * 70)

r = requests.get(
    f"{BASE}/v1/markets/history",
    params={"category": "daily-temperature", "limit": 100},
    headers=HEADERS,
    timeout=20,
)
print(f"HTTP {r.status_code}")
j = r.json() if r.ok else {}
ms = j.get("markets", []) if isinstance(j, dict) else j
print(f"markets returned: {len(ms) if isinstance(ms, list) else 'n/a'}")
if isinstance(ms, list) and ms:
    print("first 3:")
    for i, m in enumerate(ms[:3]):
        keys = [
            "condition_id",
            "id",
            "slug",
            "question",
            "category",
            "end_date",
            "closed_date",
            "active",
        ]
        present = {k: m.get(k) for k in keys if k in m}
        print(f"  [{i}] {present}")
    # save all daily-temperature conditionIds
    daily_temp_cids = [
        m.get("condition_id") or m.get("id") for m in ms if isinstance(m, dict)
    ]
    daily_temp_cids = [c for c in daily_temp_cids if c]
    print(f"\nTotal daily-temperature cids: {len(daily_temp_cids)}")
    if daily_temp_cids:
        # Try fetching 1 snapshot for the first one to confirm coverage
        print(f"\n  Probing first daily-temperature cid: {daily_temp_cids[0]}")
        r = requests.get(
            f"{BASE}/v1/markets/{daily_temp_cids[0]}/snapshots",
            params={"limit": 3, "interval": "1h"},
            headers=HEADERS,
            timeout=20,
        )
        print(f"  HTTP {r.status_code}")
        j = r.json() if r.ok else {}
        snaps = j.get("snapshots", j.get("data", [])) if isinstance(j, dict) else j
        n = len(snaps) if isinstance(snaps, list) else 0
        print(f"  snapshots returned: {n}")
        if n > 0:
            print(f"  snapshot[0] keys: {list(snaps[0].keys())}")
            for k in (
                "timestamp",
                "ts",
                "mid",
                "mid_price",
                "yes_price",
                "best_bid",
                "best_ask",
            ):
                if k in snaps[0]:
                    print(f"    {k}: {snaps[0][k]}")

# ---------------------------------------------------------------------------
# 2) Lookup one of OUR slugs in ResolvedMarkets
# ---------------------------------------------------------------------------

print("\n" + "=" * 70)
print("2) Lookup our Polymarket slugs in ResolvedMarkets (by-slug endpoint)")
print("=" * 70)

sys.path.insert(0, ".")
from data_pipeline.unified_datastore import UnifiedDatastore  # noqa: E402

ds = UnifiedDatastore()
m = ds.read_markets()
# Pick 5 markets with slugs
sample = m[m["slug"].notna()].head(5)
print(f"Probing {len(sample)} of our slugs via /v1/markets/by-slug/...")

for i, row in enumerate(sample.itertuples(index=False)):
    slug = row.slug
    q = (row.question or "")[:60]
    print(f"\n  [{i}] slug={slug!r}  q={q!r}")
    r = requests.get(
        f"{BASE}/v1/markets/by-slug/{slug}",
        headers=HEADERS,
        timeout=15,
    )
    print(f"       HTTP {r.status_code}")
    if r.ok:
        j = r.json()
        if isinstance(j, dict):
            keys = [
                "condition_id",
                "id",
                "slug",
                "question",
                "category",
                "end_date",
                "active",
            ]
            present = {k: j.get(k) for k in keys if k in j}
            print(f"       body: {present}")
        else:
            print(f"       body: {str(j)[:200]}")
    else:
        print(f"       body: {r.text[:200]}")
    time.sleep(0.3)

# ---------------------------------------------------------------------------
# 3) Pull all weather category historical markets and inspect slugs
# ---------------------------------------------------------------------------

print("\n" + "=" * 70)
print("3) Inspect /v1/markets/history?category=weather&limit=100 slugs")
print("=" * 70)

r = requests.get(
    f"{BASE}/v1/markets/history",
    params={"category": "weather", "limit": 100},
    headers=HEADERS,
    timeout=20,
)
print(f"HTTP {r.status_code}")
j = r.json() if r.ok else {}
ms = j.get("markets", []) if isinstance(j, dict) else j
print(f"markets: {len(ms) if isinstance(ms, list) else 'n/a'}")
if isinstance(ms, list) and ms:
    print("\nFirst 5 weather history markets:")
    for i, m in enumerate(ms[:5]):
        keys = [
            "condition_id",
            "id",
            "slug",
            "question",
            "category",
            "end_date",
            "closed_date",
        ]
        present = {k: m.get(k) for k in keys if k in m}
        print(f"  [{i}] {present}")
    # show all distinct slugs
    slugs = sorted(
        {m.get("slug", "") for m in ms if isinstance(m, dict) and m.get("slug")}
    )
    print(f"\nDistinct weather slugs ({len(slugs)}):")
    for s in slugs[:20]:
        print(f"  - {s}")
