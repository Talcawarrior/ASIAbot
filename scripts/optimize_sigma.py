"""Sigma optimization: compute per-city optimal sigma from calibration data.

The sigma parameter in the normal CDF controls how "sharp" the probability
forecast is. A small sigma (e.g. 2.0) means the model is very confident
about small deviations from the threshold. A large sigma (e.g. 5.0) means
even large deviations only shift the probability moderately.

Optimal sigma is the one that minimizes Brier score on historical data:
  sigma_optimal = std(predicted_value - actual_value) per city

This captures the actual forecast uncertainty for each city.
"""

import json
import logging
import os
import sqlite3

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("SIGMA_OPT")

DB_PATH = "data/bot.db"
SIGMA_PATH = "data/city_sigma.json"


def compute_city_sigma():
    """Compute optimal sigma per city from historical calibration data."""
    conn = sqlite3.connect(DB_PATH)
    cal = pd.read_sql(
        "SELECT city, date, model, predicted_value, actual_value, days_ahead FROM historical_calibrations",
        conn,
    )
    conn.close()

    if cal.empty:
        logger.error("No calibration data found")
        return {}

    # Compute error per (city, model)
    cal["error"] = cal["predicted_value"] - cal["actual_value"]

    # Per-city sigma (across all models and dates)
    city_sigma = {}
    for city in sorted(cal["city"].unique()):
        city_data = cal[cal["city"] == city]
        errors = city_data["error"].dropna()
        if len(errors) < 10:
            logger.warning("City %s: only %d errors, using global sigma", city, len(errors))
            continue
        sigma = errors.std()
        # Clamp sigma to reasonable range [1.0, 10.0]
        sigma = max(1.0, min(10.0, sigma))
        city_sigma[city] = round(sigma, 3)
        logger.info(
            "  %s: sigma=%.2f (n=%d, mean_error=%.2f, range=[%.1f, %.1f])",
            city,
            sigma,
            len(errors),
            errors.mean(),
            errors.min(),
            errors.max(),
        )

    # Also compute per-model sigma
    model_sigma = {}
    for model in sorted(cal["model"].unique()):
        model_data = cal[cal["model"] == model]
        errors = model_data["error"].dropna()
        if len(errors) < 5:
            continue
        sigma = errors.std()
        sigma = max(1.0, min(10.0, sigma))
        model_sigma[model] = round(sigma, 3)
        logger.info("  Model %s: sigma=%.2f (n=%d)", model, sigma, len(errors))

    # Global sigma
    all_errors = cal["error"].dropna()
    global_sigma = round(max(1.0, min(10.0, all_errors.std())), 3)
    logger.info("  Global: sigma=%.2f (n=%d)", global_sigma, len(all_errors))

    result = {
        "city_sigma": city_sigma,
        "model_sigma": model_sigma,
        "global_sigma": global_sigma,
        "n_cities": len(city_sigma),
        "n_total_rows": len(cal),
    }

    # Save
    os.makedirs(os.path.dirname(SIGMA_PATH), exist_ok=True)
    with open(SIGMA_PATH, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Saved sigma data to %s", SIGMA_PATH)

    return result


if __name__ == "__main__":
    result = compute_city_sigma()
    print(json.dumps(result, indent=2))
