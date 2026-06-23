"""Fast async backfill of snapshot_yes_price using concurrent CLOB requests.

Usage:
    PYTHONPATH=/home/z/my-project/ASIAbot python3 scripts/backfill_snapshot_yes_price_fast.py [--concurrency 10] [--rate-sleep 0.05]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import aiohttp  # noqa: E402
import pandas as pd  # noqa: E402

from data_pipeline.unified_datastore import UnifiedDatastore  # noqa: E402

CLOB = "https://clob.polymarket.com"
SNAPSHOT_BACKFILL_PATH = REPO / "data" / "unified" / "markets_snapshot_prices.parquet"

_LOG_FILE = REPO / "logs" / "snapshot_backfill_fast.log"
REPO.joinpath("logs").mkdir(exist_ok=True)
_fh = open(_LOG_FILE, "a")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    stream=_fh,
)
log = logging.getLogger("backfill_fast")
log.info("=== NEW RUN ===")


async def fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    yes_token: str,
    end_ts: pd.Timestamp,
    window_h: float = 23.5,
) -> float | None:
    """Fetch CLOB price for one token. Returns price or None."""
    start_ts = end_ts - pd.Timedelta(hours=window_h)
    params = {
        "market": str(yes_token),
        "startTs": int(start_ts.timestamp()),
        "endTs": int(end_ts.timestamp()),
        "fidelity": 60,
    }
    for attempt in range(2):  # max 2 retries
        async with sem:
            try:
                async with session.get(
                    f"{CLOB}/prices-history",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as r:
                    if r.status == 429:
                        await asyncio.sleep(min(10.0, 2.0 * (2**attempt)))
                        continue
                    if r.status == 400:
                        return None
                    r.raise_for_status()
                    j = await r.json()
                    history = j.get("history", [])
                    if history:
                        return float(history[0].get("p", 0.0))
                    return None
            except (asyncio.TimeoutError, Exception):
                if attempt == 0:
                    await asyncio.sleep(0.3)
                continue
    return None


async def main_async(args):
    ds = UnifiedDatastore()
    markets = ds.read_markets()
    log.info("Loaded %d markets", len(markets))

    has_token = markets["clob_token_ids"].notna() & (
        markets["clob_token_ids"].astype(str) != "[]"
    )
    eligible = markets[has_token].copy().reset_index(drop=True)
    log.info("Eligible: %d", len(eligible))

    # Load cache
    cache: dict[str, float] = {}
    if SNAPSHOT_BACKFILL_PATH.exists():
        try:
            cached_df = pd.read_parquet(SNAPSHOT_BACKFILL_PATH)
            for _, r in cached_df.iterrows():
                cache[r["condition_id"]] = float(r["snapshot_yes_price"])
            log.info("Loaded %d cached prices", len(cache))
        except Exception as exc:
            log.warning("Cache load failed: %s", exc)

    # Separate cached vs need-fetch
    need_fetch = []
    results = [None] * len(eligible)
    for i, row in enumerate(eligible.itertuples(index=False)):
        cid = row.condition_id
        if cid in cache:
            results[i] = cache[cid]
        else:
            need_fetch.append((i, row))

    log.info(
        "Cached: %d, Need fetch: %d",
        sum(1 for x in results if x is not None),
        len(need_fetch),
    )
    if not need_fetch:
        log.info("Nothing to fetch!")
        return results, eligible, markets, ds, cache

    sem = asyncio.Semaphore(args.concurrency)
    connector = aiohttp.TCPConnector(
        limit=args.concurrency, limit_per_host=args.concurrency
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        batch_size = 200
        total_fetched = 0
        for batch_start in range(0, len(need_fetch), batch_size):
            batch = need_fetch[batch_start : batch_start + batch_size]
            tasks = []
            for idx, row in batch:
                try:
                    token_ids = row.clob_token_ids
                    try:
                        token_ids = list(token_ids)
                    except TypeError:
                        token_ids = [token_ids]
                    yes_token = token_ids[0] if token_ids else None
                    if not yes_token:
                        results[idx] = None
                        continue
                    end_ts = pd.Timestamp(row.end_date)
                    if end_ts.tz is None:
                        end_ts = end_ts.tz_localize("UTC")
                    else:
                        end_ts = end_ts.tz_convert("UTC")
                    tasks.append((idx, fetch_one(session, sem, yes_token, end_ts)))
                except Exception:
                    results[idx] = None

            # Run batch concurrently
            batch_results = await asyncio.gather(
                *[t[1] for t in tasks], return_exceptions=True
            )
            for j, val in enumerate(batch_results):
                idx = tasks[j][0]
                if isinstance(val, Exception):
                    results[idx] = None
                elif val is not None:
                    results[idx] = val
                    cache[eligible.iloc[idx]["condition_id"]] = val

            total_fetched += len(batch)
            hit = sum(1 for x in results if x is not None)
            log.info(
                "Progress: %d/%d fetched, %d/%d total hit (%.1f%%)",
                total_fetched,
                len(need_fetch),
                hit,
                len(eligible),
                100.0 * hit / len(eligible),
            )

            # Checkpoint every batch
            ckpt_df = pd.DataFrame(
                [
                    {
                        "condition_id": eligible.iloc[i]["condition_id"],
                        "snapshot_yes_price": v,
                    }
                    for i, v in enumerate(results)
                    if v is not None
                ]
            )
            ckpt_df.to_parquet(SNAPSHOT_BACKFILL_PATH, index=False)

            if args.rate_sleep > 0:
                await asyncio.sleep(args.rate_sleep)

    return results, eligible, markets, ds, cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=15, help="parallel requests")
    ap.add_argument(
        "--rate-sleep", type=float, default=0.1, help="sleep between batches"
    )
    args = ap.parse_args()

    start = time.time()
    results, eligible, markets, ds, cache = asyncio.run(main_async(args))
    elapsed = time.time() - start

    eligible["snapshot_yes_price"] = results
    hit = eligible["snapshot_yes_price"].notna().sum()
    log.info(
        "Snapshot prices found: %d / %d (%.1f%%) in %.1fs",
        hit,
        len(eligible),
        100.0 * hit / max(1, len(eligible)),
        elapsed,
    )

    # Merge back
    augmented = markets.merge(
        eligible[["condition_id", "snapshot_yes_price"]],
        on="condition_id",
        how="left",
        suffixes=("", "_new"),
    )
    if "snapshot_yes_price" in markets.columns:
        augmented["snapshot_yes_price"] = augmented[
            "snapshot_yes_price_new"
        ].combine_first(augmented["snapshot_yes_price"])
        augmented = augmented.drop(columns=["snapshot_yes_price_new"])

    ds.write_markets(augmented)
    log.info("Updated unified datastore")

    median_p = float(eligible["snapshot_yes_price"].dropna().median() or 0.0)
    log.info("=" * 60)
    log.info("Backfill complete in %.1fs", elapsed)
    log.info("  Markets:    %d", len(markets))
    log.info("  With price: %d  (%.1f%%)", hit, 100.0 * hit / max(1, len(eligible)))
    log.info("  Median price: %.4f", median_p)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
