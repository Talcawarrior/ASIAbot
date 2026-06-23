"""Backfill 90+ days of resolved Polymarket weather markets into the unified
datastore so walk-forward OOS evaluation becomes possible.

The current ``data/unified/markets.parquet`` only spans 3 days (Apr 15-17
2026) because that's all the live scraper has seen. Karpathy / ASI / SIA
loops backtest on this narrow window and overfit (the 2-model dominance
issue from QA-11 was a symptom of exactly this).

Approach
--------
Polymarket's ``/markets`` endpoint is paginated and biased toward
high-volume politics/sports markets — weather markets get pushed out
beyond the 2000-row offset cap. The ``/public-search?q=...`` endpoint
returns weather markets cleanly (5 events per page, ~11 markets per
event, paginated by ``page=N``). Each query returns ~6200 events
matching "highest temperature" alone — enough to cover years of history.

This script:
  1. For each query in {highest temperature, lowest temperature, rain,
     snow}, paginates ``/public-search`` until events older than
     ``--days`` are reached or ``--max-pages`` is hit.
  2. Flattens the nested ``events[*].markets[*]`` into a single DataFrame
     of weather markets.
  3. Filters to ``closed=true`` (resolved) markets only.
  4. Parses city / threshold / target_date from each question using
     ``engine.market_parser.MarketParser`` (same parser the live bot uses,
     so backtest distribution matches live distribution).
  5. Looks up lat/lon via ``scrapers.polymarket.PolymarketScraper.get_city_coords``.
  6. Maps Gamma's snake-case fields to the unified schema and merges with
     the existing markets.parquet (dedupe by ``market_id``, prefer newly
     fetched rows so re-resolutions propagate).
  7. Writes the merged table back to ``data/unified/markets.parquet``.
  8. Reports row count, date span, and per-city breakdown so we can sanity
     check before running ``backfill_snapshot_yes_price.py`` and the
     walk-forward OOS evaluation.

Usage:
    set -a && source .env && set +a
    python scripts/backfill_gamma_markets.py [--days 120] [--max-pages 200]
                                              [--dry-run] [--queries ...]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from data_pipeline.unified_datastore import (  # noqa: E402
    UNIFIED_MARKETS_SCHEMA,
    UnifiedDatastore,
)
from engine.market_parser import MarketParser  # noqa: E402
from scrapers.polymarket import PolymarketScraper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)-24s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("backfill_gamma")
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

GAMMA_BASE = "https://gamma-api.polymarket.com"
PUBLIC_SEARCH = f"{GAMMA_BASE}/public-search"
DEFAULT_QUERIES = ("highest temperature", "lowest temperature")
DEFAULT_PAGE_TIMEOUT = 30.0
INTER_PAGE_DELAY_S = 0.20  # be polite — 5 req/s ceiling


# Shared session with connection pooling
_SESSION = requests.Session()
_ADAPTER = requests.adapters.HTTPAdapter(
    pool_connections=4,
    pool_maxsize=8,
    max_retries=0,
)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)


# ---------------------------------------------------------------------------
# Field mapping: Gamma API (camelCase / snake_case) -> unified schema
# ---------------------------------------------------------------------------

GAMMA_TO_UNIFIED = {
    "id": "market_id",
    "question": "question",
    "slug": "slug",
    "conditionId": "condition_id",
    "endDate": "end_date",
    "closedTime": "closed_time",
    "volume": "volume",
    "liquidity": "liquidity",
    "clobTokenIds": "clob_token_ids",
    # yes_price / no_price / resolved_outcome are derived below.
}


def _safe_json_loads(val):
    if val is None or val == "":
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _extract_outcome_price(outcomes, prices, side: str) -> float | None:
    """Extract YES or NO final outcome price from Gamma market fields."""
    if not isinstance(prices, list) or not isinstance(outcomes, list):
        return None
    if len(prices) != len(outcomes):
        return None
    target = "yes" if side.lower() == "yes" else "no"
    for label, price in zip(outcomes, prices):
        if str(label).strip().lower() == target:
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
    # Fallback: assume first=YES, second=NO
    if side.lower() == "yes" and len(prices) >= 1:
        try:
            return float(prices[0])
        except (TypeError, ValueError):
            return None
    if side.lower() == "no" and len(prices) >= 2:
        try:
            return float(prices[1])
        except (TypeError, ValueError):
            return None
    return None


def _extract_resolved_outcome(yes_p, no_p) -> str | None:
    if yes_p is None or no_p is None:
        return None
    if yes_p == 1.0 and no_p == 0.0:
        return "Yes"
    if no_p == 1.0 and yes_p == 0.0:
        return "No"
    return None


# ---------------------------------------------------------------------------
# /public-search pagination
# ---------------------------------------------------------------------------


def fetch_weather_events_page(query: str, page: int) -> tuple[list[dict], bool]:
    """Fetch one page of /public-search?q=...&page=N.

    Returns (events, has_more). Empty list + has_more=False on hard error.
    """
    for attempt in range(4):
        try:
            r = _SESSION.get(
                PUBLIC_SEARCH,
                params={"q": query, "page": page},
                timeout=DEFAULT_PAGE_TIMEOUT,
            )
            if r.status_code == 429:
                wait = min(60.0, 2.0 * (2**attempt))
                log.warning("429 on page=%d — backoff %.1fs", page, wait)
                time.sleep(wait)
                continue
            if r.status_code == 422:
                # Validation error — bad params. Don't retry.
                log.warning("422 on page=%d (query=%r) — stopping", page, query)
                return [], False
            r.raise_for_status()
            data = r.json()
            events = data.get("events", []) or []
            has_more = bool(data.get("pagination", {}).get("hasMore", False))
            return events, has_more
        except (requests.Timeout, requests.ConnectionError) as exc:
            wait = 0.5 * (2**attempt)
            log.warning(
                "network err on page=%d (%s) — retry %.1fs",
                page,
                type(exc).__name__,
                wait,
            )
            time.sleep(wait)
        except Exception as exc:
            log.warning("unexpected err on page=%d: %s", page, exc)
            time.sleep(0.5)
            return [], False
    log.warning("page=%d failed after 4 attempts — treating as end", page)
    return [], False


def fetch_weather_markets(
    queries: list[str],
    *,
    min_end_date: datetime | None = None,
    max_pages: int = 200,
) -> pd.DataFrame:
    """Paginate /public-search for each query, flatten markets.

    Stops paginating a query when either:
      - has_more=False
      - max_pages reached
      - All 5 events on a page have endDate < min_end_date (we've gone past
        the window we care about)

    Returns a DataFrame with all Gamma market fields plus derived
    yes_price / no_price / resolved_outcome columns.
    """
    all_markets: list[dict] = []
    for query in queries:
        log.info(
            "Query %r — paginating up to %d pages (min_end_date=%s)",
            query,
            max_pages,
            min_end_date,
        )
        n_markets_this_query = 0
        for page in range(1, max_pages + 1):
            events, has_more = fetch_weather_events_page(query, page)
            if not events:
                log.info("  page %d: empty — stopping query %r", page, query)
                break

            page_markets_count = 0
            min_end_on_page: datetime | None = None
            for ev in events:
                ev_end = ev.get("endDate")
                if ev_end:
                    try:
                        ev_end_dt = pd.to_datetime(ev_end, utc=True).to_pydatetime()
                        if min_end_on_page is None or ev_end_dt < min_end_on_page:
                            min_end_on_page = ev_end_dt
                    except Exception:
                        pass

                for m in ev.get("markets", []) or []:
                    # Attach event-level fields for downstream parsing
                    m.setdefault("_event_title", ev.get("title"))
                    m.setdefault("_event_endDate", ev_end)
                    all_markets.append(m)
                    page_markets_count += 1
            n_markets_this_query += page_markets_count

            if page % 10 == 0 or page == 1 or not has_more:
                log.info(
                    "  page %d: +%d markets (cumulative for query: %d, total: %d)  has_more=%s",
                    page,
                    page_markets_count,
                    n_markets_this_query,
                    len(all_markets),
                    has_more,
                )

            if not has_more:
                log.info(
                    "  has_more=False at page %d — done with query %r", page, query
                )
                break

            # Early stop ONLY if EVERY event on this page is older than min_end_date.
            # We can't stop on a single old event because public-search returns
            # results out of strict date order — page N may have events from
            # May, Jun, and Feb all mixed together.
            if min_end_date and min_end_on_page:
                # Check newest event on the page — if even the newest is older
                # than min_end_date, we've truly exhausted the window.
                page_end_dates = [
                    pd.to_datetime(e.get("endDate"), utc=True).to_pydatetime()
                    for e in events
                    if e.get("endDate")
                ]
                if page_end_dates and max(page_end_dates) < min_end_date:
                    log.info(
                        "  page %d: NEWEST endDate %s < min_end_date %s — stopping query %r",
                        page,
                        max(page_end_dates),
                        min_end_date,
                        query,
                    )
                    break

            time.sleep(INTER_PAGE_DELAY_S)

    if not all_markets:
        return pd.DataFrame()

    df = pd.DataFrame(all_markets)
    log.info("Total raw markets fetched across %d queries: %d", len(queries), len(df))

    # Dedupe by id (queries may overlap)
    if "id" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["id"], keep="last").reset_index(drop=True)
        log.info("Dedupe by id: %d -> %d", before, len(df))

    # Parse JSON-encoded fields
    for col in ("outcomes", "outcomePrices", "clobTokenIds"):
        if col in df.columns:
            df[col] = df[col].apply(_safe_json_loads)

    # Derive YES/NO outcome prices and resolved outcome
    df["yes_price"] = df.apply(
        lambda r: _extract_outcome_price(
            r.get("outcomes"), r.get("outcomePrices"), "yes"
        ),
        axis=1,
    )
    df["no_price"] = df.apply(
        lambda r: _extract_outcome_price(
            r.get("outcomes"), r.get("outcomePrices"), "no"
        ),
        axis=1,
    )
    df["resolved_outcome"] = df.apply(
        lambda r: _extract_resolved_outcome(r.get("yes_price"), r.get("no_price")),
        axis=1,
    )

    # Filter to closed markets only
    if "closed" in df.columns:
        n_before = len(df)
        df = df[df["closed"] == True].reset_index(drop=True)  # noqa: E712
        log.info("Filter closed=true: %d -> %d", n_before, len(df))

    return df


# ---------------------------------------------------------------------------
# Schema transform
# ---------------------------------------------------------------------------


def _coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dtypes to match UNIFIED_MARKETS_SCHEMA."""
    out = pd.DataFrame(index=df.index)
    for col, dtype in UNIFIED_MARKETS_SCHEMA.items():
        if col in df.columns:
            try:
                if dtype.startswith("datetime64"):
                    out[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                elif dtype == "float64":
                    out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
                elif dtype == "str":
                    out[col] = df[col].astype("string")
                else:
                    out[col] = df[col].astype(dtype, errors="ignore")
            except Exception as exc:
                log.warning("coerce %s -> %s failed: %s", col, dtype, exc)
                out[col] = pd.NA
        else:
            if dtype.startswith("datetime64"):
                out[col] = pd.NaT
            elif dtype == "float64":
                out[col] = pd.NA
            elif dtype == "object":
                out[col] = pd.NA
            else:
                out[col] = pd.NA
    out = out[out["market_id"].notna()].reset_index(drop=True)
    return out


def _parse_market_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Run MarketParser on every question to derive city/threshold/target_date."""
    parser = MarketParser()
    cities: list[str | None] = []
    city_codes: list[str] = []
    thresholds: list[float] = []
    threshold_units: list[str] = []
    market_types: list[str] = []
    target_dates: list[pd.Timestamp | pd.NaT] = []
    lats: list[float] = []
    lons: list[float] = []

    for q in df["question"].fillna(""):
        city = parser._extract_city(q) or ""
        cities.append(city)
        city_codes.append(city)
        thr = parser._extract_threshold(q)
        if thr:
            thresholds.append(float(thr[0]))
            threshold_units.append(thr[1] or "celsius")
        else:
            thresholds.append(0.0)
            threshold_units.append("celsius")
        q_lower = q.lower()
        if any(
            w in q_lower for w in ("above", "higher", "over", "exceed", "hot", "warm")
        ):
            mtype = "HIGH"
        elif any(w in q_lower for w in ("below", "under", "lower", "cold")):
            mtype = "LOW"
        else:
            mtype = "HIGH"
        market_types.append(mtype)
        try:
            td = parser._extract_date(q)
        except Exception:
            td = None
        target_dates.append(pd.Timestamp(td, tz="UTC") if td else pd.NaT)
        coords = PolymarketScraper.get_city_coords(city) if city else None
        lats.append(float(coords[0]) if coords else 0.0)
        lons.append(float(coords[1]) if coords else 0.0)

    df = df.copy()
    # Title-case city to match the case in actuals.parquet (which uses
    # 'London', 'New York', 'Sao Paulo', etc.). Without this normalization
    # the build_brier_dataset join silently drops all new markets because
    # MarketParser._extract_city returns lowercase ('london', 'new york').
    df["city"] = pd.Series(cities).fillna("").str.title()
    df["city_code"] = pd.Series(city_codes).fillna("").str.title()
    df["threshold"] = thresholds
    df["threshold_unit"] = threshold_units
    df["market_type"] = market_types
    df["target_date"] = target_dates
    df["latitude"] = lats
    df["longitude"] = lons
    df["category"] = "Weather"
    return df


def _gamma_to_unified(gamma_df: pd.DataFrame) -> pd.DataFrame:
    """Map a Gamma-format DataFrame to the unified markets schema."""
    renamed = gamma_df.rename(columns=GAMMA_TO_UNIFIED)
    renamed = _parse_market_fields(renamed)
    n_before = len(renamed)
    renamed = renamed[renamed["target_date"].notna()].reset_index(drop=True)
    n_after = len(renamed)
    log.info(
        "Parsed target_date: %d / %d kept (%d dropped)",
        n_after,
        n_before,
        n_before - n_after,
    )
    n_before = len(renamed)
    renamed = renamed[
        (renamed["threshold"] != 0.0)
        & (renamed["threshold"] >= -40)
        & (renamed["threshold"] <= 55)
    ].reset_index(drop=True)
    n_after = len(renamed)
    log.info(
        "Sane threshold [-40, 55] °C: %d / %d kept (%d dropped)",
        n_after,
        n_before,
        n_before - n_after,
    )
    return _coerce_schema(renamed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--days",
        type=int,
        default=120,
        help="how many days back to fetch (default 120)",
    )
    ap.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="end date YYYY-MM-DD (default: today UTC)",
    )
    ap.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="max pages per query (5 events/page; default 200)",
    )
    ap.add_argument(
        "--queries",
        nargs="+",
        default=list(DEFAULT_QUERIES),
        help="search queries to use (default: 'highest temperature' 'lowest temperature')",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch + parse, but don't write markets.parquet",
    )
    args = ap.parse_args()

    if args.end_date:
        end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
    else:
        end_dt = datetime.now(UTC)
    min_end_dt = end_dt - timedelta(days=args.days)
    end_str = end_dt.strftime("%Y-%m-%d")
    min_str = min_end_dt.strftime("%Y-%m-%d")
    log.info(
        "Backfill window: %s -> %s (last %d days, anything older is dropped)",
        min_str,
        end_str,
        args.days,
    )
    log.info("Queries: %s", args.queries)
    log.info("Max pages per query: %d (5 events per page)", args.max_pages)

    # 1. Fetch all weather markets via /public-search
    gamma_df = fetch_weather_markets(
        list(args.queries),
        min_end_date=min_end_dt,
        max_pages=args.max_pages,
    )
    if gamma_df.empty:
        log.error("No markets returned — aborting")
        return 1
    log.info("Gamma weather markets (after closed=true + dedupe): %d", len(gamma_df))

    # Filter to endDate >= min_end_dt
    if "endDate" in gamma_df.columns:
        end_ts = pd.to_datetime(gamma_df["endDate"], utc=True, errors="coerce")
        n_before = len(gamma_df)
        keep_mask = (end_ts.isna()) | (end_ts >= pd.Timestamp(min_end_dt))
        gamma_df = gamma_df[keep_mask].reset_index(drop=True)
        log.info("Filter endDate >= %s: %d -> %d", min_str, n_before, len(gamma_df))

    # 2. Map to unified schema (parses city/threshold/target_date)
    unified_new = _gamma_to_unified(gamma_df)
    log.info("Unified new rows (after parse + filter): %d", len(unified_new))
    if unified_new.empty:
        log.error("All rows dropped during parse — aborting")
        return 1

    log.info(
        "New rows target_date span: %s -> %s",
        unified_new["target_date"].min(),
        unified_new["target_date"].max(),
    )
    log.info("New rows city breakdown (top 15):")
    for city, n in unified_new["city"].value_counts().head(15).items():
        log.info("  %-20s %d", city, n)

    # 3. Load existing markets.parquet and merge
    ds = UnifiedDatastore()
    existing = ds.read_markets()
    log.info("Existing markets.parquet: %d rows", len(existing))

    if existing.empty:
        merged = unified_new
    else:
        existing["market_id"] = existing["market_id"].astype(str)
        unified_new["market_id"] = unified_new["market_id"].astype(str)
        merged = pd.concat([existing, unified_new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["market_id"], keep="last")
        merged = merged.reset_index(drop=True)
    log.info("Merged: %d rows (dedup by market_id)", len(merged))

    # 4. Stats
    log.info("=" * 60)
    log.info("Final markets.parquet will contain:")
    log.info("  rows:        %d", len(merged))
    log.info(
        "  date span:   %s -> %s",
        merged["target_date"].min(),
        merged["target_date"].max(),
    )
    n_unique_dates = merged["target_date"].dt.date.nunique()
    log.info("  unique target_dates: %d", n_unique_dates)
    log.info(
        "  resolved:    %d (yes_price in {0,1})",
        int(merged["yes_price"].isin([0.0, 1.0]).sum()),
    )
    if "clob_token_ids" in merged.columns:
        clob_mask = (
            merged["clob_token_ids"].notna()
            & (merged["clob_token_ids"].astype(str) != "[]")
            & (merged["clob_token_ids"].astype(str) != "")
        )
        log.info("  with clob_token_ids: %d", int(clob_mask.sum()))
    if "snapshot_yes_price" in merged.columns:
        log.info(
            "  with snapshot_yes_price: %d",
            int(merged["snapshot_yes_price"].notna().sum()),
        )
    log.info("=" * 60)

    if args.dry_run:
        log.info("DRY RUN — not writing to markets.parquet")
        return 0

    # 5. Write back — preserve snapshot_yes_price if present
    if "snapshot_yes_price" in merged.columns:
        snap = merged[["market_id", "snapshot_yes_price"]].dropna()
        merged_write = merged.drop(columns=["snapshot_yes_price"])
        ds.write_markets(merged_write)
        log.info(
            "Wrote %d rows to markets.parquet (snapshot_yes_price saved for re-merge)",
            len(merged_write),
        )
        time.sleep(0.5)
        written = ds.read_markets()
        if not snap.empty:
            written = written.merge(snap, on="market_id", how="left")
            ds.write_markets(written)
            log.info(
                "Re-merged %d snapshot_yes_price values back into markets.parquet",
                len(snap),
            )
    else:
        ds.write_markets(merged)
        log.info("Wrote %d rows to markets.parquet", len(merged))

    return 0


if __name__ == "__main__":
    sys.exit(main())
