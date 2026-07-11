"""Stratified RMSE backfill for historical_calibrations table.

Fetches 16-day forecasts from Open-Meteo Historical Forecast API
at different lead times (days_ahead 0-15), compares with actual
observations, and calculates RMSE per horizon.

Usage:
    python scripts/rmse_stratified_backfill.py --cities 10 --days 30
"""

import argparse
import json
import logging
import math
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("RMSE_BACKFILL")

DB_PATH = "data/bot.db"

# 10 diverse cities for good coverage
BACKFILL_CITIES = [
    ("New York", "KLGA", 40.78, -73.97),
    ("London", "EGLL", 51.47, -0.46),
    ("Tokyo", "RJTT", 35.76, 140.39),
    ("Sydney", "YSSY", -33.95, 151.18),
    ("Dubai", "OMDB", 25.25, 55.36),
    ("São Paulo", "SBGR", -23.43, -46.47),
    ("Seoul", "RKSS", 37.56, 126.98),
    ("Munich", "EDDM", 48.35, 11.79),
    ("Toronto", "CYYZ", 43.68, -79.63),
    ("Wellington", "NZWN", -41.33, 174.81),
]

# Models available in Historical Forecast API
API_MODELS = "gfs_seamless,ecmwf_ifs04,gem_seamless,icon_seamless,jma_seamless"
MODEL_MAP = {
    "gfs_seamless": "gfs_seamless",
    "ecmwf_ifs04": "ecmwf_ifs025",
    "gem_seamless": "gem_global",
    "icon_seamless": "icon_global",
    "jma_seamless": "jma_seamless",
}


def init_table():
    """Ensure historical_calibrations has days_ahead column."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Check if days_ahead column exists
    c.execute("PRAGMA table_info(historical_calibrations)")
    cols = {row[1] for row in c.fetchall()}
    if "days_ahead" not in cols:
        c.execute("ALTER TABLE historical_calibrations ADD COLUMN days_ahead INTEGER")
        logger.info("Added days_ahead column to historical_calibrations")
    conn.commit()
    conn.close()


def fetch_forecast(http, lat, lon, start, end):
    """Fetch historical forecast from Open-Meteo."""
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
    """Fetch actual observations from Open-Meteo Archive API."""
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


def run_backfill(cities_count=10, past_days=30, max_lead=15):
    """Main backfill: for each city, fetch forecasts at different lead times."""
    init_table()

    cities = BACKFILL_CITIES[:cities_count]
    now = datetime.now(UTC)
    # End date: 2 days ago (archive fully complete)
    end_dt = now - timedelta(days=2)
    # Start date: enough room for max_lead days of lookback
    start_dt = end_dt - timedelta(days=past_days)

    http = requests.Session()
    retries = Retry(total=3, backoff_factor=2, allowed_methods=["GET"])
    http.mount("https://", HTTPAdapter(max_retries=retries))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    total_inserted = 0
    rmse_data = {}  # {days_ahead: [(bias_max, bias_min), ...]}

    for city_name, icao, lat, lon in cities:
        logger.info("Processing %s (%s)...", city_name, icao)

        # 1. Fetch actual observations for the full range
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

        # Build actual lookup: date -> (max, min)
        actual_map = {}
        for i, d in enumerate(actual_dates):
            amax = actual_maxs[i] if i < len(actual_maxs) else None
            amin = actual_mins[i] if i < len(actual_mins) else None
            if amax is not None or amin is not None:
                actual_map[d] = (amax, amin)

        # 2. For each lead time, fetch forecasts
        for lead in range(max_lead + 1):
            # Forecast request: from (target_start - lead) to target_end
            # This gives us forecasts made `lead` days before each target date
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

            for i, f_date in enumerate(f_dates):
                # The target date is f_date + lead days
                target_dt = datetime.strptime(f_date, "%Y-%m-%d") + timedelta(days=lead)
                target_date = target_dt.strftime("%Y-%m-%d")

                if target_date not in actual_map:
                    continue

                act_max, act_min = actual_map[target_date]

                for api_m, internal_m in MODEL_MAP.items():
                    # Max temperature
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
                        total_inserted += 1

                        if lead not in rmse_data:
                            rmse_data[lead] = []
                        rmse_data[lead].append(bias)

                    # Min temperature
                    pred_min_key = f"temperature_2m_min_{api_m}"
                    pred_min = forecasts.get(pred_min_key, [])[i] if pred_min_key in forecasts else None

                    if pred_min is not None and act_min is not None:
                        bias = round(pred_min - act_min, 3)
                        cursor.execute(
                            """INSERT OR REPLACE INTO historical_calibrations
                            (city_code, city, date, metric, model, predicted_value, actual_value, bias, days_ahead)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                icao,
                                city_name,
                                target_date,
                                "temperature_min",
                                internal_m,
                                pred_min,
                                act_min,
                                bias,
                                lead,
                            ),
                        )
                        total_inserted += 1

                        if lead not in rmse_data:
                            rmse_data[lead] = []
                        rmse_data[lead].append(bias)

            conn.commit()
            time.sleep(0.5)  # Rate limit courtesy

    conn.close()

    # 3. Calculate RMSE per horizon
    logger.info("\n=== RMSE BY HORIZON ===")
    rmse_by_horizon = {}
    for lead in sorted(rmse_data.keys()):
        biases = rmse_data[lead]
        if not biases:
            continue
        mse = sum(b**2 for b in biases) / len(biases)
        rmse = math.sqrt(mse)
        rmse_by_horizon[lead] = round(rmse, 2)
        logger.info("  days_ahead=%d: RMSE=%.2f°C (n=%d)", lead, rmse, len(biases))

    # 4. Save results
    results_path = "data/rmse_by_horizon.json"
    with open(results_path, "w") as f:
        json.dump(rmse_by_horizon, f, indent=2)
    logger.info("Results saved to %s", results_path)

    logger.info("\nTotal records inserted: %d", total_inserted)
    return rmse_by_horizon


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cities", type=int, default=10)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-lead", type=int, default=15)
    args = parser.parse_args()

    run_backfill(args.cities, args.days, args.max_lead)
