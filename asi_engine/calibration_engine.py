"""Calibration Engine for ASIbot.

Calculates the Mean Bias Error (MBE) and Mean Absolute Error (MAE) for each
model per city and metric, then provides real-time "fine-tuned" temperature
calibrations to eliminate systematic bias.

Continuous calibration design:
  - Rolling window: only the last ROLLING_WINDOW_DAYS of observations are
    used, so the bias map tracks regime shifts (season changes, model
    version updates) instead of averaging over the entire history.
  - Recency weighting: within the window, more recent observations count
    more (exponential decay), so a bias that appeared last week outweighs
    one from 55 days ago even inside the same window.
  - Shrinkage: city-model pairs with few samples get pulled toward 0 bias
    (i.e. "trust the raw forecast") proportional to how little data backs
    them, so a single unlucky day doesn't produce a large, noisy offset.
"""

import json
import logging
import math
import os
from datetime import UTC, datetime, timedelta

from database.db import DB_PATH, get_session
from database.models import HistoricalCalibration

logger = logging.getLogger("ASI_CALIBRATION")

CALIBRATION_JSON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "data", "asi_calibration.json")
)

# --- Continuous calibration knobs -------------------------------------------------
ROLLING_WINDOW_DAYS = 60  # only look at the last N days of observations
RECENCY_HALF_LIFE_DAYS = 14  # weight halves every N days within the window
MIN_SAMPLES_FOR_FULL_TRUST = 20  # samples needed before applying the full correction


def _parse_dt(date_str):
    """Best-effort parse of a date string from sqlite into an aware datetime."""
    if date_str is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str[:26], fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(date_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


class CalibrationEngine:
    """Computes systematic model bias and applies real-time temperature calibrations."""

    def __init__(self):
        self.db_path = DB_PATH
        self.bias_map = {}
        self.load_calibration_map()

    def calculate_biases(self) -> dict:
        """Query recent historical calibrations and calculate a recency-weighted,
        shrunk bias for each city-model pair.

        Computes weighted MAE and MBE over a rolling window, saves them to a
        local JSON config, and returns it.
        """
        logger.info(
            "ASI Calibration: Calculating systematic model biases (rolling %dd window, %dd half-life)...",
            ROLLING_WINDOW_DAYS,
            RECENCY_HALF_LIFE_DAYS,
        )

        cutoff = datetime.now(UTC) - timedelta(days=ROLLING_WINDOW_DAYS)

        # Pull raw rows (not pre-aggregated) so we can apply recency weights
        # and shrinkage in Python before collapsing to one row per group.
        with get_session() as session:
            try:
                rows = (
                    session.query(
                        HistoricalCalibration.city_code,
                        HistoricalCalibration.city,
                        HistoricalCalibration.metric,
                        HistoricalCalibration.model,
                        HistoricalCalibration.bias,
                        HistoricalCalibration.date,
                    )
                    .filter(HistoricalCalibration.date >= cutoff)
                    .all()
                )
            except Exception as e:
                logger.warning("ASI Calibration: historical_calibrations table is empty or query failed: %s", e)
                return {}

        if not rows:
            logger.warning(
                "ASI Calibration: no observations in the last %d days. "
                "Keeping previous bias map (%d cities) unchanged.",
                ROLLING_WINDOW_DAYS,
                len(self.bias_map),
            )
            return self.bias_map

        now = datetime.now(UTC)
        groups: dict[tuple, list[tuple]] = {}
        for city_code, city, metric, model, bias, date_str in rows:
            if bias is None:
                continue
            key = (city_code, city, metric, model)
            groups.setdefault(key, []).append((bias, date_str))

        new_bias_map = {}
        decay_lambda = math.log(2) / RECENCY_HALF_LIFE_DAYS

        for (city_code, city, metric, model), observations in groups.items():
            weighted_bias_sum = 0.0
            weighted_abs_bias_sum = 0.0
            weight_sum = 0.0

            for bias, date_str in observations:
                obs_date = _parse_dt(date_str)
                age_days = max((now - obs_date).total_seconds() / 86400.0, 0.0) if obs_date else 0.0
                w = math.exp(-decay_lambda * age_days)
                weighted_bias_sum += w * bias
                weighted_abs_bias_sum += w * abs(bias)
                weight_sum += w

            count = len(observations)
            raw_mbe = weighted_bias_sum / weight_sum if weight_sum > 0 else 0.0
            raw_mae = weighted_abs_bias_sum / weight_sum if weight_sum > 0 else 0.0

            # Shrinkage: pull mbe toward 0 when sample count is low, so a
            # city-model pair with 2 observations doesn't get a full-strength
            # correction. trust_factor -> 1.0 as count grows past the threshold.
            trust_factor = min(count / MIN_SAMPLES_FOR_FULL_TRUST, 1.0)
            shrunk_mbe = raw_mbe * trust_factor

            if city_code not in new_bias_map:
                new_bias_map[city_code] = {"city_name": city, "metrics": {}}
            if metric not in new_bias_map[city_code]["metrics"]:
                new_bias_map[city_code]["metrics"][metric] = {}

            new_bias_map[city_code]["metrics"][metric][model] = {
                "mbe": round(shrunk_mbe, 3),  # Recency-weighted, shrunk Mean Bias Error (+ = overpredicting)
                "mae": round(raw_mae, 3),  # Recency-weighted Mean Absolute Error
                "sample_count": count,
                "trust_factor": round(trust_factor, 3),
                "window_days": ROLLING_WINDOW_DAYS,
                "computed_at": now.isoformat(),
            }

        # Save to disk
        try:
            os.makedirs(os.path.dirname(CALIBRATION_JSON_PATH), exist_ok=True)
            with open(CALIBRATION_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(new_bias_map, f, indent=2, sort_keys=True)
            logger.info(
                "ASI Calibration: Successfully persisted calibration models to %s",
                CALIBRATION_JSON_PATH,
            )
        except Exception as e:
            logger.error("ASI Calibration: Could not save calibration map: %s", e)

        self.bias_map = new_bias_map
        return new_bias_map

    def load_calibration_map(self):
        """Load the pre-computed bias correction parameters from disk."""
        if os.path.exists(CALIBRATION_JSON_PATH):
            try:
                with open(CALIBRATION_JSON_PATH, encoding="utf-8") as f:
                    self.bias_map = json.load(f)
                logger.info(
                    "ASI Calibration: Loaded bias parameters for %d cities from disk.",
                    len(self.bias_map),
                )
            except Exception as e:
                logger.warning("ASI Calibration: Could not load calibration JSON: %s", e)

    def get_calibrated_temperature(self, city_code: str, metric: str, model: str, raw_temp: float) -> float:
        """Apply dynamic temperature bias correction (fine-tuning).

        If a model has a systematic bias for this city (e.g. overpredicts by 1.5C),
        we subtract the Mean Bias Error (MBE) to get the true, fine-tuned value.
        """
        # Strip internal suffix if any
        clean_metric = (
            "temperature_max"
            if metric.lower() == "temperature_max" or (metric.lower().startswith("temp") and "max" in metric.lower())
            else "temperature_min"
        )

        if city_code in self.bias_map:
            metrics_map = self.bias_map[city_code].get("metrics", {})
            if clean_metric in metrics_map:
                model_map = metrics_map[clean_metric].get(model, {})
                mbe = model_map.get("mbe", 0.0)

                # Apply Calibration: true_temp = raw_temp - MBE
                calibrated = round(raw_temp - mbe, 2)
                logger.debug(
                    "ASI Calibration [%s - %s]: Corrected %s raw=%.2fC -> calibrated=%.2fC (MBE=%.2fC)",
                    city_code,
                    model,
                    clean_metric,
                    raw_temp,
                    calibrated,
                    mbe,
                )
                return calibrated

        return raw_temp
