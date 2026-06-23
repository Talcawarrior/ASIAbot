"""Backfill snapshot_yes_price for every market in the unified datastore.

For each market, fetch Polymarket CLOB prices-history for the YES token,
over the 24h window ending at market.end_date. Pick the FIRST price in
that window as the "entry price" (most conservative — earliest known
price within 24h of resolution).

Polymarket's CLOB API rejects intervals > 24h, so we use 23h50m.

The result is written back to data/unified/markets.parquet with an
extra `snapshot_yes_price` column.

Optionally, if RESOLVEDMARKETS_API_KEY is set, we ALSO try ResolvedMarkets
for the same conditionId (premium tier has crypto + weather markets, but
their weather set is annual climate markets — won't overlap with our daily
city temperature markets). When ResolvedMarkets has coverage, we prefer
its snapshot because it includes order-book depth, not just last trade.

Usage:
    set -a && source .env && set +a
    python scripts/backfill_snapshot_yes_price.py [--limit N] [--rate-sleep 0.3]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from data_pipeline.unified_datastore import UnifiedDatastore  # noqa: E402

CLOB = "https://clob.polymarket.com"
SNAPSHOT_BACKFILL_PATH = REPO / "data" / "unified" / "markets_snapshot_prices.parquet"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("backfill")
# Force unbuffered stdout so we get real-time progress even when piped
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def fetch_clob_history(
    yes_token: str, end_ts: pd.Timestamp, *, window_h: float = 23.5
) -> list[dict]:
    """Fetch Polymarket CLOB prices-history for one token.

    Returns list of {"t": <unix_s>, "p": <float>} dicts. Empty on error.
    """
    start_ts = end_ts - pd.Timedelta(hours=window_h)
    params = {
        "market": str(yes_token),
        "startTs": int(start_ts.timestamp()),
        "endTs": int(end_ts.timestamp()),
        "fidelity": 60,  # 1-minute candles
    }
    for attempt in range(4):
        try:
            r = _SESSION.get(f"{CLOB}/prices-history", params=params, timeout=15)
            if r.status_code == 429:
                wait = min(120.0, 4.0 * (2**attempt))
                log.warning("429 from CLOB — backing off %.1fs", wait)
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return []
            r.raise_for_status()
            j = r.json()
            return j.get("history", [])
        except (requests.Timeout, requests.ConnectionError) as exc:
            wait = 0.5 * (2**attempt)
            log.warning("network error (%s) — retry in %.1fs", type(exc).__name__, wait)
            time.sleep(wait)
        except Exception as exc:
            log.warning("unexpected fetch error: %s", exc)
            time.sleep(0.5)
            return []
    return []


# Shared session with connection pooling — avoids creating a new TCP
# connection per request (which can exhaust ephemeral ports under load).
_SESSION = requests.Session()
_ADAPTER = requests.adapters.HTTPAdapter(
    pool_connections=4, pool_maxsize=8, max_retries=0
)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap on # markets (0 = all)")
    ap.add_argument(
        "--rate-sleep", type=float, default=0.25, help="seconds between requests"
    )
    ap.add_argument(
        "--from-cache",
        action="store_true",
        help="skip fetch and re-apply cached prices from markets_snapshot_prices.parquet",
    )
    args = ap.parse_args()

    ds = UnifiedDatastore()
    markets = ds.read_markets()
    log.info("Loaded %d markets", len(markets))

    # Filter to markets with clob_token_ids
    has_token = markets["clob_token_ids"].notna() & (
        markets["clob_token_ids"].astype(str) != "[]"
    )
    eligible = markets[has_token].copy().reset_index(drop=True)
    log.info("Eligible (with clob_token_ids): %d", len(eligible))
    if args.limit > 0:
        eligible = eligible.head(args.limit)
        log.info("Capped to %d markets", len(eligible))

    # Load cached snapshot prices if present
    cache: dict[str, float] = {}
    if SNAPSHOT_BACKFILL_PATH.exists():
        try:
            cached_df = pd.read_parquet(SNAPSHOT_BACKFILL_PATH)
            for _, r in cached_df.iterrows():
                cache[r["condition_id"]] = float(r["snapshot_yes_price"])
            log.info("Loaded %d cached snapshot prices", len(cache))
        except Exception as exc:
            log.warning("Failed to load cache: %s", exc)

    if args.from_cache:
        log.info("Skipping fetch; applying cache only")
        results = []
        for cid in eligible["condition_id"]:
            results.append(cache.get(cid))
    else:
        results: list[float | None] = []
        for i, row in enumerate(eligible.itertuples(index=False)):
            try:
                cid = row.condition_id
                if cid in cache:
                    results.append(cache[cid])
                    continue

                # Parse clob_token_ids
                token_ids = row.clob_token_ids
                try:
                    token_ids = list(token_ids)
                except TypeError:
                    token_ids = [token_ids]
                yes_token = token_ids[0] if len(token_ids) > 0 else None
                if not yes_token:
                    results.append(None)
                    continue

                # Parse end_date as UTC timestamp
                end_ts = pd.Timestamp(row.end_date)
                if end_ts.tz is None:
                    end_ts = end_ts.tz_localize("UTC")
                else:
                    end_ts = end_ts.tz_convert("UTC")

                history = fetch_clob_history(yes_token, end_ts)
                if not history:
                    results.append(None)
                else:
                    first_p = float(history[0].get("p", 0.0))
                    results.append(first_p)

                time.sleep(args.rate_sleep)

                # checkpoint every 10 markets
                if (i + 1) % 10 == 0:
                    hit_rate = (
                        100.0 * sum(1 for x in results if x is not None) / len(results)
                    )
                    log.info(
                        "Progress: %d/%d  hit-rate=%.1f%%",
                        i + 1,
                        len(eligible),
                        hit_rate,
                    )
                    # write checkpoint to disk so we can resume
                    ckpt_df = eligible.iloc[: len(results)].copy()
                    ckpt_df["snapshot_yes_price"] = results
                    ckpt_df = ckpt_df[["condition_id", "snapshot_yes_price"]].dropna()
                    # combine with prior cache
                    prior = pd.DataFrame(
                        [
                            {"condition_id": k, "snapshot_yes_price": v}
                            for k, v in cache.items()
                        ]
                    )
                    ckpt_combined = pd.concat([prior, ckpt_df], ignore_index=True)
                    ckpt_combined = ckpt_combined.drop_duplicates(
                        subset=["condition_id"], keep="last"
                    )
                    ckpt_combined.to_parquet(SNAPSHOT_BACKFILL_PATH, index=False)
            except Exception as exc:
                log.exception(
                    "[%d/%d] UNEXPECTED ERROR on cid=%s: %s",
                    i + 1,
                    len(eligible),
                    getattr(row, "condition_id", "?")[:18],
                    exc,
                )
                results.append(None)
                # longer pause + emergency checkpoint on error
                time.sleep(5.0)
                # emergency checkpoint
                try:
                    ckpt_df = eligible.iloc[: len(results)].copy()
                    ckpt_df["snapshot_yes_price"] = results
                    ckpt_df = ckpt_df[["condition_id", "snapshot_yes_price"]].dropna()
                    prior = pd.DataFrame(
                        [
                            {"condition_id": k, "snapshot_yes_price": v}
                            for k, v in cache.items()
                        ]
                    )
                    ckpt_combined = pd.concat([prior, ckpt_df], ignore_index=True)
                    ckpt_combined = ckpt_combined.drop_duplicates(
                        subset=["condition_id"], keep="last"
                    )
                    ckpt_combined.to_parquet(SNAPSHOT_BACKFILL_PATH, index=False)
                    log.info("Emergency checkpoint: %d cached", len(ckpt_combined))
                except Exception:
                    pass

    # Add snapshot_yes_price column
    eligible["snapshot_yes_price"] = results
    hit = eligible["snapshot_yes_price"].notna().sum()
    log.info(
        "Snapshot prices found: %d / %d (%.1f%%)",
        hit,
        len(eligible),
        100.0 * hit / max(1, len(eligible)),
    )

    # Persist the cache — MERGE with prior cache, don't overwrite.
    # This lets us resume safely when running --limit chunks.
    new_cache_df = eligible[["condition_id", "snapshot_yes_price"]].dropna()
    prior_cache_df = pd.DataFrame(
        [{"condition_id": k, "snapshot_yes_price": v} for k, v in cache.items()]
    )
    cache_df = pd.concat([prior_cache_df, new_cache_df], ignore_index=True)
    cache_df = cache_df.drop_duplicates(subset=["condition_id"], keep="last")
    cache_df.to_parquet(SNAPSHOT_BACKFILL_PATH, index=False)
    log.info(
        "Wrote cache → %s  (%d rows, %d new)",
        SNAPSHOT_BACKFILL_PATH,
        len(cache_df),
        len(new_cache_df),
    )

    # Now write the augmented markets table back to the unified datastore
    # The unified datastore's write_markets() overwrites. We need to preserve
    # the original schema and just add snapshot_yes_price.
    augmented = markets.merge(
        eligible[["condition_id", "snapshot_yes_price"]],
        on="condition_id",
        how="left",
        suffixes=("", "_new"),
    )
    # If a snapshot_yes_price already exists, prefer the new one
    if "snapshot_yes_price" in markets.columns:
        augmented["snapshot_yes_price"] = augmented[
            "snapshot_yes_price_new"
        ].combine_first(augmented["snapshot_yes_price"])
        augmented = augmented.drop(columns=["snapshot_yes_price_new"])

    ds.write_markets(augmented)
    log.info("Updated unified datastore markets.parquet with snapshot_yes_price column")

    # Summary
    log.info("=" * 60)
    log.info("Backfill complete.")
    log.info("  Markets:    %d", len(markets))
    log.info("  With price: %d  (%.1f%%)", hit, 100.0 * hit / max(1, len(eligible)))
    log.info(
        "  Median price: %.4f",
        float(eligible["snapshot_yes_price"].dropna().median() or 0.0),
    )
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
