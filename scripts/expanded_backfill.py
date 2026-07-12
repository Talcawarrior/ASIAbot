"""Expanded backfill: 18 cities × 30 days × 8 models.

Fetches historical forecasts from Open-Meteo, compares with actuals,
and populates historical_calibrations with full coverage.
"""

import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("BACKFILL")

DB_PATH = "data/bot.db"

# All 18 cities from brier_df with coordinates
ALL_CITIES = [
    ("Amsterdam", "EHAM", 52.31, 4.77),
    ("Busan", "RKPK", 35.18, 128.93),
    ("Dubai", "OMDB", 25.25, 55.36),
    ("Guangzhou", "ZGGG", 23.39, 113.30),
    ("Helsinki", "EFHK", 60.32, 24.95),
    ("Istanbul", "LTFM", 41.26, 28.74),
    ("Jeddah", "OEJN", 21.67, 39.16),
    ("London", "EGLL", 51.47, -0.46),
    ("Manila", "RPLL", 14.51, 121.02),
    ("Munich", "EDDM", 48.35, 11.79),
    ("New York", "KLGA", 40.78, -73.97),
    ("Qingdao", "ZSQD", 36.07, 120.38),
    ("Seoul", "RKSS", 37.56, 126.98),
    ("Sydney", "YSSY", -33.95, 151.18),
    ("São Paulo", "SBGR", -23.43, -46.47),
    ("Tokyo", "RJTT", 35.76, 140.39),
    ("Toronto", "CYYZ", 43.68, -79.63),
    ("Wellington", "NZWN", -41.33, 174.81),
]

API_MODELS = (
    "gfs_seamless,ecmwf_ifs025,gem_global,icon_global,jma_seamless,cma_grapes_global,ukmo_seamless,meteofrance_seamless"
)
MODEL_MAP = {
    "gfs_seamless": "gfs_seamless",
    "ecmwf_ifs025": "ecmwf_ifs025",
    "gem_global": "gem_global",
    "icon_global": "icon_global",
    "jma_seamless": "jma_seamless",
    "cma_grapes_global": "cma_grapes_global",
    "ukmo_seamless": "ukmo_seamless",
    "meteofrance_seamless": "meteofrance_seamless",
}


def init_table():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA table_info(historical_calibrations)")
    cols = {row[1] for row in c.fetchall()}
    if "days_ahead" not in cols:
        c.execute("ALTER TABLE historical_calibrations ADD COLUMN days_ahead INTEGER")
    conn.commit()
    conn.close()


def fetch_forecast(http, lat, lon, start, end):
    url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "models": API_MODELS,
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }
    resp = http.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return None
    return resp.json().get("daily", {})


def fetch_actuals(http, lat, lon, start, end):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }
    resp = http.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return None
    return resp.json().get("daily", {})


def run_backfill(past_days=30, max_lead=15):
    init_table()

    now = datetime.now(UTC)
    end_dt = now - timedelta(days=2)
    start_dt = end_dt - timedelta(days=past_days)

    http = requests.Session()
    retries = Retry(total=3, backoff_factor=2, allowed_methods=["GET"])
    http.mount("https://", HTTPAdapter(max_retries=retries))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check existing coverage to avoid re-fetching
    cursor.execute("SELECT city, COUNT(DISTINCT date) FROM historical_calibrations GROUP BY city")
    existing = {row[0]: row[1] for row in cursor.fetchall()}

    total_inserted = 0
    cities_to_fetch = []

    for city_name, icao, lat, lon in ALL_CITIES:
        city_rows = existing.get(city_name, 0)
        if city_rows >= past_days * 6:  # ~6 models per day is "enough"
            logger.info("Skipping %s (already %d rows)", city_name, city_rows)
            continue
        cities_to_fetch.append((city_name, icao, lat, lon))

    logger.info("Fetching %d cities, %d days, %d lead times", len(cities_to_fetch), past_days, max_lead)

    for city_name, icao, lat, lon in cities_to_fetch:
        logger.info("Processing %s (%s)...", city_name, icao)

        actuals = fetch_actuals(
            http,
            lat,
            lon,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
        )
        if not actuals:
            logger.warning("  No actuals for %s, skipping", city_name)
            continue

        actual_dates = actuals.get("time", [])
        actual_maxs = actuals.get("temperature_2m_max", [])
        actual_mins = actuals.get("temperature_2m_min", [])

        actual_map = {}
        for i, d in enumerate(actual_dates):
            amax = actual_maxs[i] if i < len(actual_maxs) else None
            amin = actual_mins[i] if i < len(actual_mins) else None
            if amax is not None:
                actual_map[d] = (amax, amin)

        for lead in range(max_lead + 1):
            f_start = start_dt - timedelta(days=lead)
            f_end = end_dt - timedelta(days=lead)

            forecasts = fetch_forecast(
                http,
                lat,
                lon,
                f_start.strftime("%Y-%m-%d"),
                f_end.strftime("%Y-%m-%d"),
            )
            if not forecasts:
                continue

            f_dates = forecasts.get("time", [])
            city_inserted = 0

            for i, f_date in enumerate(f_dates):
                target_dt = datetime.strptime(f_date, "%Y-%m-%d") + timedelta(days=lead)
                target_date = target_dt.strftime("%Y-%m-%d")

                if target_date not in actual_map:
                    continue

                act_max, act_min = actual_map[target_date]

                for api_m, internal_m in MODEL_MAP.items():
                    pred_max_key = f"temperature_2m_max_{api_m}"
                    pred_max = forecasts.get(pred_max_key, [])[i] if pred_max_key in forecasts else None

                    if pred_max is not None and act_max is not None:
                        bias = round(pred_max - act_max, 3)
                        cursor.execute(
                            """INSERT OR REPLACE INTO historical_calibrations
                            (city_code, city, date, metric, model, predicted_value, actual_value, bias, days_ahead)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                icao,
                                city_name,
                                target_date,
                                "temperature_max",
                                internal_m,
                                pred_max,
                                act_max,
                                bias,
                                lead,
                            ),
                        )
                        city_inserted += 1

            total_inserted += city_inserted
            if lead % 5 == 0:
                logger.info("  Lead %d/%d: %d rows inserted", lead, max_lead, city_inserted)
                conn.commit()

        conn.commit()
        logger.info("  Total for %s: %d rows", city_name, city_inserted)

        # Small delay between cities to respect rate limits
        time.sleep(1)

    conn.close()
    logger.info("Backfill complete. Total inserted: %d", total_inserted)
    return total_inserted


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="Past days to backfill")
    parser.add_argument("--lead", type=int, default=15, help="Max lead time in days")
    args = parser.parse_args()
    run_backfill(past_days=args.days, max_lead=args.lead)
