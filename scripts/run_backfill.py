#!/usr/bin/env python3
"""Standalone backfill runner that logs to file and handles errors."""
import sys, os, time, asyncio, logging
from pathlib import Path

REPO = Path("/home/z/my-project/ASIAbot")
sys.path.insert(0, str(REPO))
os.chdir(REPO)

LOG_PATH = REPO / "logs" / "backfill_progress.log"
REPO.joinpath("logs").mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOG_PATH), level=logging.INFO,
    format="%(asctime)s %(message)s", filemode="a"
)
log = logging.getLogger()
log.info("=== START ===")

try:
    import pandas as pd
    import aiohttp
    from data_pipeline.unified_datastore import UnifiedDatastore

    CLOB = "https://clob.polymarket.com"
    CACHE_PATH = REPO / "data" / "unified" / "markets_snapshot_prices.parquet"

    ds = UnifiedDatastore()
    markets = ds.read_markets()
    log.info("Markets: %d", len(markets))

    has_token = markets["clob_token_ids"].notna() & (markets["clob_token_ids"].astype(str) != "[]")
    eligible = markets[has_token].copy().reset_index(drop=True)

    cache = {}
    if CACHE_PATH.exists():
        cdf = pd.read_parquet(CACHE_PATH)
        for _, r in cdf.iterrows():
            cache[r["condition_id"]] = float(r["snapshot_yes_price"])
    log.info("Cache: %d, Eligible: %d, Need: %d", len(cache), len(eligible), len(eligible) - len(set(eligible["condition_id"]) & set(cache.keys())))

    async def fetch_price(session, sem, token, end_ts):
        start_ts = end_ts - pd.Timedelta(hours=23.5)
        params = {"market": str(token), "startTs": int(start_ts.timestamp()), "endTs": int(end_ts.timestamp()), "fidelity": 60}
        for _ in range(2):
            async with sem:
                try:
                    async with session.get(f"{CLOB}/prices-history", params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        if r.status in (400, 404):
                            return None
                        if r.status == 429:
                            await asyncio.sleep(3)
                            continue
                        r.raise_for_status()
                        j = await r.json()
                        h = j.get("history", [])
                        return float(h[0]["p"]) if h else None
                except Exception:
                    await asyncio.sleep(0.2)
        return None

    async def run():
        need = []
        results = [None] * len(eligible)
        for i, row in eligible.iterrows():
            if row.condition_id in cache:
                results[i] = cache[row.condition_id]
            else:
                need.append((i, row))

        log.info("Cached results: %d, Need fetch: %d", sum(1 for x in results if x is not None), len(need))
        if not need:
            return results

        sem = asyncio.Semaphore(20)
        conn = aiohttp.TCPConnector(limit=20)
        async with aiohttp.ClientSession(connector=conn) as session:
            batch_size = 300
            done = 0
            for bs in range(0, len(need), batch_size):
                batch = need[bs:bs+batch_size]
                tasks = []
                for idx, row in batch:
                    try:
                        tids = list(row.clob_token_ids) if hasattr(row.clob_token_ids, '__iter__') else [row.clob_token_ids]
                        yt = tids[0] if tids else None
                        if not yt:
                            results[idx] = None
                            continue
                        ets = pd.Timestamp(row.end_date)
                        if ets.tz is None:
                            ets = ets.tz_localize("UTC")
                        tasks.append((idx, fetch_price(session, sem, yt, ets)))
                    except Exception:
                        results[idx] = None

                vals = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
                for j, v in enumerate(vals):
                    idx = tasks[j][0]
                    price = None if isinstance(v, Exception) else v
                    results[idx] = price
                    if price is not None:
                        cache[eligible.iloc[idx]["condition_id"]] = price

                done += len(batch)
                hit = sum(1 for x in results if x is not None)
                log.info("Fetched %d/%d | Total hit %d/%d (%.1f%%)", done, len(need), hit, len(eligible), 100*hit/len(eligible))

                # checkpoint
                ckpt = pd.DataFrame([{"condition_id": eligible.iloc[i]["condition_id"], "snapshot_yes_price": v} for i, v in enumerate(results) if v is not None])
                ckpt.to_parquet(CACHE_PATH, index=False)

        return results

    results = asyncio.run(run())

    eligible["snapshot_yes_price"] = results
    hit = eligible["snapshot_yes_price"].notna().sum()
    log.info("DONE: %d/%d (%.1f%%)", hit, len(eligible), 100*hit/len(eligible))

    augmented = markets.merge(eligible[["condition_id", "snapshot_yes_price"]], on="condition_id", how="left", suffixes=("", "_new"))
    if "snapshot_yes_price" in markets.columns:
        augmented["snapshot_yes_price"] = augmented["snapshot_yes_price_new"].combine_first(augmented["snapshot_yes_price"])
        augmented = augmented.drop(columns=["snapshot_yes_price_new"])
    ds.write_markets(augmented)
    log.info("Markets parquet updated")

except Exception as e:
    log.exception("FATAL: %s", e)

log.info("=== END ===")