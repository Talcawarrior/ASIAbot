"""Test how many of our 1210 Polymarket weather conditionIds ResolvedMarkets
actually has snapshots for. Picks 10 random ones and probes.

Run:
    set -a && source .env && set +a
    python scripts/probe_resolvedmarkets_snapshots.py
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

BASE = "https://api.resolvedmarkets.com"
API_KEY = os.environ.get("RESOLVEDMARKETS_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY}

from data_pipeline.unified_datastore import UnifiedDatastore  # noqa: E402

ds = UnifiedDatastore()
m = ds.read_markets()
print(f"Loaded {len(m)} markets from unified datastore")

# Filter to weather + non-empty conditionId
weather = m[
    (m["category"] == "Weather") & m["condition_id"].notna() & (m["condition_id"] != "")
]
print(f"Weather markets with conditionId: {len(weather)}")

# Sample 10 random ones
random.seed(42)
sample = weather.sample(min(10, len(weather)))
print(f"\nProbing {len(sample)} random conditionIds...\n")

found = 0
not_found = 0
errs = 0
sample_snapshot = None

for i, row in enumerate(sample.itertuples(index=False)):
    cid = row.condition_id
    end = row.end_date
    q = (row.question or "")[:60]
    print(f"  [{i}] cid={cid[:18]}... end_date={end}  q={q!r}")

    # Try fetching 1 snapshot at 1d interval to minimize API calls
    r = requests.get(
        f"{BASE}/v1/markets/{cid}/snapshots",
        params={"limit": 5, "interval": "1d"},
        headers=HEADERS,
        timeout=20,
    )
    if r.status_code == 404:
        print("       404 — ResolvedMarkets does not track this market")
        not_found += 1
        continue
    if r.status_code == 429:
        print("       429 — rate limited; backing off 10s")
        time.sleep(10)
        # retry once
        r = requests.get(
            f"{BASE}/v1/markets/{cid}/snapshots",
            params={"limit": 5, "interval": "1d"},
            headers=HEADERS,
            timeout=20,
        )
    if not r.ok:
        print(f"       HTTP {r.status_code}: {r.text[:150]}")
        errs += 1
        continue

    j = r.json()
    snaps = j.get("snapshots", j.get("data", [])) if isinstance(j, dict) else j
    n = len(snaps) if isinstance(snaps, list) else 0
    print(f"       OK — {n} snapshots returned")
    if n > 0:
        found += 1
        if sample_snapshot is None:
            sample_snapshot = snaps[0]
            print(f"       sample snapshot keys: {list(snaps[0].keys())}")
            # show a few interesting fields
            for k in (
                "timestamp",
                "ts",
                "mid",
                "mid_price",
                "yes_price",
                "best_bid",
                "best_ask",
                "spread",
                "depth",
                "total_bid_depth",
                "total_ask_depth",
            ):
                if k in snaps[0]:
                    print(f"       snapshot.{k}: {snaps[0][k]}")
    else:
        not_found += 1

    # Respect 4 req/s rate limit
    time.sleep(0.3)

print(
    f"\nSummary: found={found}, not_found={not_found}, errors={errs} (of {len(sample)} probed)"
)
if sample_snapshot:
    print(f"\nFull sample snapshot:\n{sample_snapshot}")
