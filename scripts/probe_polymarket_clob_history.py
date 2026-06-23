"""Probe Polymarket's CLOB prices-history endpoint for one of our daily
temperature markets. If it works, we can pull real entry-price snapshots
and use them as snapshot_yes_price in the Brier dataset.

Run:
    python scripts/probe_polymarket_clob_history.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

from data_pipeline.unified_datastore import UnifiedDatastore  # noqa: E402

ds = UnifiedDatastore()
m = ds.read_markets()
print(f"Loaded {len(m)} markets")

# Pick 3 with clob_token_ids
sample = m[
    m["clob_token_ids"].notna() & (m["clob_token_ids"].astype(str) != "[]")
].head(3)
print(f"Probing {len(sample)} markets with clob_token_ids\n")

CLOB = "https://clob.polymarket.com"

for i, row in enumerate(sample.itertuples(index=False)):
    q = (row.question or "")[:60]
    cids = row.clob_token_ids
    if isinstance(cids, str):
        # try to eval the string repr
        try:
            import json

            cids = json.loads(cids.replace("'", '"'))
        except Exception:
            cids = [cids]
    # Coerce numpy array / pandas list to plain Python list
    try:
        cids = list(cids)
    except TypeError:
        cids = [cids]
    print(f"[{i}] q={q!r}")
    print(f"     condition_id={row.condition_id}")
    print(f"     clob_token_ids={cids}")
    print(f"     end_date={row.end_date}, yes_price(resolved)={row.yes_price}")

    # YES token is conventionally clob_token_ids[0]
    yes_token = cids[0] if len(cids) > 0 else None
    if not yes_token:
        continue

    # /prices-history?market={tokenId}&startTs=...&endTs=...
    # Polymarket CLOB rejects intervals >24h. We want "entry price" —
    # the price ~24h before market resolution.
    import pandas as pd

    end_ts = pd.Timestamp(row.end_date)
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    start_ts = end_ts - pd.Timedelta(hours=23, minutes=50)
    start_s = int(start_ts.timestamp())
    end_s = int(end_ts.timestamp())

    r = requests.get(
        f"{CLOB}/prices-history",
        params={
            "market": yes_token,
            "startTs": start_s,
            "endTs": end_s,
            "fidelity": 60,
        },
        timeout=20,
    )
    print(f"     GET /prices-history HTTP {r.status_code}")
    if not r.ok:
        print(f"     body: {r.text[:200]}")
        print()
        continue

    j = r.json()
    # Expected shape: {"history": [{"t": 1234567890, "p": "0.55"}, ...]}
    history = j.get("history", [])
    print(f"     history points: {len(history)}")
    if history:
        print(f"     first: {history[0]}")
        print(f"     last:  {history[-1]}")
        # find the price closest to (end_date - 24h) as "entry price" proxy
        target_ts = end_ts.timestamp() - 86400  # 24h before resolution
        closest = min(history, key=lambda x: abs(x.get("t", 0) - target_ts))
        print(f"     price ~24h before end: {closest}")
    print()
    time.sleep(0.5)
