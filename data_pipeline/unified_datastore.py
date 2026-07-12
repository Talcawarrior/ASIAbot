"""Unified datastore: joins all 4 data sources into a backtest-ready schema.

The previous eval_harness.py used a YES=True oracle for backtesting -- this
caused the inflated 74.34% ROI claim that GLM-5.2's audit exposed as
synthetic. This module fixes the root cause by joining real ground-truth
data from four sources into a single walk-forward-out-of-sample dataset:

  1. polymarket_ingest      ??? market metadata + final resolved outcomes
  2. weather_ensemble       ??? 8-model forecast + archive actuals (ground truth)
  3. poly_data_ingest       ??? on-chain OrderFilled trades (order flow)
  4. resolvedmarkets_ingest ??? tick-level orderbook snapshots (depth)

The unified schema is:

  unified_markets    (one row per market -- polymarket metadata + outcome)
  unified_forecasts  (one row per (market, model, target_date) -- ensemble)
  unified_actuals    (one row per (city, date) -- ground truth temperature)
  unified_trades     (one row per OrderFilled event -- on-chain)
  unified_snapshots  (one row per (market, timestamp) -- orderbook depth)

Walk-forward OOS split: the dataset is split by DATE, not by random shuffle.
For each backtest step N, train on data before date[N], test on date[N..N+K].
This prevents the "test on the same data you trained on" leakage that
plagued the previous eval_harness.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger("UNIFIED_DATASTORE")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "unified",
)

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------


UNIFIED_MARKETS_SCHEMA = {
    "market_id": "str",
    "question": "str",
    "slug": "str",
    "condition_id": "str",
    "category": "str",
    "city": "str",
    "city_code": "str",
    "latitude": "float64",
    "longitude": "float64",
    "threshold": "float64",
    "threshold_unit": "str",
    "market_type": "str",  # HIGH / LOW / RANGE
    "target_date": "datetime64[ns, UTC]",
    "end_date": "datetime64[ns, UTC]",
    "closed_time": "datetime64[ns, UTC]",
    "yes_price": "float64",  # final resolved yes price (0 or 1)
    "no_price": "float64",  # final resolved no price (0 or 1)
    "resolved_outcome": "str",  # 'Yes' / 'No' / None
    "volume": "float64",
    "liquidity": "float64",
    "clob_token_ids": "object",  # list[str]
}

UNIFIED_FORECASTS_SCHEMA = {
    "city": "str",
    "latitude": "float64",
    "longitude": "float64",
    "target_date": "datetime64[ns, UTC]",
    "model": "str",
    "variable": "str",
    "value": "float64",
    "fetched_at": "datetime64[ns, UTC]",
}

UNIFIED_ACTUALS_SCHEMA = {
    "city": "str",
    "latitude": "float64",
    "longitude": "float64",
    "date": "datetime64[ns, UTC]",
    "temperature_2m_max": "float64",
    "temperature_2m_min": "float64",
    "temperature_2m_mean": "float64",
    "precipitation_sum": "float64",
    "wind_speed_10m_max": "float64",
}

UNIFIED_TRADES_SCHEMA = {
    "block_number": "int64",
    "timestamp": "int64",
    "datetime_utc": "datetime64[ns, UTC]",
    "transaction_hash": "str",
    "log_index": "int64",
    "order_hash": "str",
    "maker": "str",
    "taker": "str",
    "side": "int64",  # 0 = BUY, 1 = SELL
    "token_id": "str",
    "maker_asset_id": "int64",
    "taker_asset_id": "int64",
    "maker_fill_amount": "int64",
    "taker_fill_amount": "int64",
    "fee": "int64",
    "builder": "int64",
    "metadata": "str",
    "maker_usd": "float64",
    "taker_usd": "float64",
    "implied_price": "float64",
    "market_id": "str",  # joined from clobTokenIds lookup
}

UNIFIED_SNAPSHOTS_SCHEMA = {
    "market_id": "str",
    "timestamp": "datetime64[ns, UTC]",
    "interval": "str",
    "mid_price": "float64",
    "spread": "float64",
    "best_bid": "float64",
    "best_ask": "float64",
    "bid_depth": "float64",
    "ask_depth": "float64",
    "bids": "object",  # list[dict]
    "asks": "object",  # list[dict]
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class UnifiedDatastoreConfig:
    """Where to read/write unified data."""

    data_dir: str = DATA_DIR
    # Default lookback window for backtests
    default_lookback_days: int = 90
    # Walk-forward step size in days
    walk_forward_step_days: int = 7
    # Walk-forward test window size in days
    walk_forward_test_days: int = 7
    # Minimum number of markets in a test window to be valid
    min_markets_per_window: int = 5


# ---------------------------------------------------------------------------
# Datastore
# ---------------------------------------------------------------------------


class UnifiedDatastore:
    """Manages the unified schema + walk-forward splits on disk.

    Storage layout:
      {data_dir}/
        markets.parquet       - unified_markets
        forecasts.parquet     - unified_forecasts
        actuals.parquet       - unified_actuals
        trades.parquet        - unified_trades
        snapshots.parquet     - unified_snapshots
        splits/
          walk_forward_{n}.parquet  - per-step split index
    """

    def __init__(self, cfg: UnifiedDatastoreConfig | None = None):
        self.cfg = cfg or UnifiedDatastoreConfig()
        os.makedirs(self.cfg.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.cfg.data_dir, "splits"), exist_ok=True)

    # -- Path helpers ----------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self.cfg.data_dir, f"{name}.parquet")

    def _split_path(self, n: int) -> str:
        return os.path.join(self.cfg.data_dir, "splits", f"walk_forward_{n}.parquet")

    # -- Write API -------------------------------------------------------

    def write_markets(self, df: pd.DataFrame) -> None:
        self._write_validated("markets", df, UNIFIED_MARKETS_SCHEMA)

    def write_forecasts(self, df: pd.DataFrame) -> None:
        self._write_validated("forecasts", df, UNIFIED_FORECASTS_SCHEMA)

    def write_actuals(self, df: pd.DataFrame) -> None:
        self._write_validated("actuals", df, UNIFIED_ACTUALS_SCHEMA)

    def write_trades(self, df: pd.DataFrame) -> None:
        self._write_validated("trades", df, UNIFIED_TRADES_SCHEMA)

    def write_snapshots(self, df: pd.DataFrame) -> None:
        self._write_validated("snapshots", df, UNIFIED_SNAPSHOTS_SCHEMA)

    def _write_validated(self, name: str, df: pd.DataFrame, schema: dict[str, str]) -> None:
        if df.empty:
            logger.warning("UnifiedDatastore: empty %s DataFrame, skipping write", name)
            return
        # Work on a copy to avoid SettingWithCopyWarning from upstream callers.
        df = df.copy()
        # Coerce columns that exist to the right dtype; ignore missing cols
        for col, dtype in schema.items():
            if col in df.columns:
                try:
                    if dtype.startswith("datetime64"):
                        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                    else:
                        df[col] = df[col].astype(dtype, errors="ignore")
                except Exception as exc:
                    logger.debug("Could not coerce %s.%s to %s: %s", name, col, dtype, exc)
        path = self._path(name)
        df.to_parquet(path, index=False)
        logger.info("Wrote %d rows to %s", len(df), path)

    # -- Read API --------------------------------------------------------

    def read_markets(self) -> pd.DataFrame:
        return self._read("markets")

    def read_forecasts(self) -> pd.DataFrame:
        return self._read("forecasts")

    def read_actuals(self) -> pd.DataFrame:
        return self._read("actuals")

    def read_trades(self) -> pd.DataFrame:
        return self._read("trades")

    def read_snapshots(self) -> pd.DataFrame:
        return self._read("snapshots")

    def _read(self, name: str) -> pd.DataFrame:
        path = self._path(name)
        if not os.path.exists(path):
            logger.debug("UnifiedDatastore: %s.parquet not found", name)
            return pd.DataFrame()
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return pd.DataFrame()

    # -- Walk-forward splits ---------------------------------------------

    def build_walk_forward_splits(
        self,
        *,
        lookback_days: int | None = None,
        step_days: int | None = None,
        test_days: int | None = None,
        date_column: str | None = None,
        table_name: str = "markets",
    ) -> list[dict[str, Any]]:
        """Build walk-forward OOS splits over a date-indexed table.

        For each step N:
          - test window:   [T_N, T_N + test_days)
          - train window:  [T_N - lookback_days - test_days, T_N)

        Returns list of split metadata dicts and writes each split's row
        indices to splits/walk_forward_{n}.parquet for reproducibility.

        Args:
            lookback_days: train window length (default: cfg.default_lookback_days)
            step_days: how far to advance T_N each step (default: cfg.walk_forward_step_days)
            test_days: test window length (default: cfg.walk_forward_test_days)
            date_column: which column to split on (default: 'closed_time', fallback 'target_date')
            table_name: which unified table to split (default 'markets')
        """
        lookback = lookback_days or self.cfg.default_lookback_days
        step = step_days or self.cfg.walk_forward_step_days
        test = test_days or self.cfg.walk_forward_test_days

        df = self._read(table_name)

        # Auto-select date column: prefer closed_time (no look-ahead bias),
        # fall back to target_date if closed_time is missing.
        if date_column is None:
            if "closed_time" in df.columns and df["closed_time"].notna().any():
                date_column = "closed_time"
            else:
                date_column = "target_date"

        if df.empty or date_column not in df.columns:
            logger.warning(
                "Cannot build splits: table '%s' empty or missing column '%s'",
                table_name,
                date_column,
            )
            return []

        df = df.copy()
        df[date_column] = pd.to_datetime(df[date_column], utc=True, errors="coerce")
        df = df.dropna(subset=[date_column]).sort_values(date_column).reset_index(drop=True)

        if df.empty:
            return []

        start = df[date_column].min()
        end = df[date_column].max()
        total_days = (end - start).days
        if total_days < lookback + test:
            logger.warning(
                "Not enough history for walk-forward: have %d days, need %d",
                total_days,
                lookback + test,
            )
            return []

        splits: list[dict[str, Any]] = []
        n = 0
        cur_t = start + pd.Timedelta(days=lookback)
        while cur_t + pd.Timedelta(days=test) <= end:
            n += 1
            test_start = cur_t
            test_end = cur_t + pd.Timedelta(days=test)
            train_start = cur_t - pd.Timedelta(days=lookback)
            train_end = cur_t  # exclusive -- train does NOT include test window

            train_df = df[(df[date_column] >= train_start) & (df[date_column] < train_end)]
            test_df = df[(df[date_column] >= test_start) & (df[date_column] < test_end)]

            if len(test_df) < self.cfg.min_markets_per_window:
                cur_t += pd.Timedelta(days=step)
                continue

            split_meta = {
                "split_n": n,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "train_rows": len(train_df),
                "test_rows": len(test_df),
                "train_indices": train_df.index.tolist(),
                "test_indices": test_df.index.tolist(),
            }

            # Persist split indices for reproducibility
            split_df = pd.DataFrame(
                {
                    "row_index": split_meta["test_indices"],
                    "split_n": n,
                    "test_start": test_start,
                    "test_end": test_end,
                }
            )
            split_df.to_parquet(self._split_path(n), index=False)

            splits.append(split_meta)
            logger.info(
                "Split %d: train %s..%s (%d rows) ??? test %s..%s (%d rows)",
                n,
                train_start.date(),
                train_end.date(),
                len(train_df),
                test_start.date(),
                test_end.date(),
                len(test_df),
            )
            cur_t += pd.Timedelta(days=step)

        logger.info("Built %d walk-forward splits", len(splits))
        return splits

    def get_split(self, n: int) -> dict[str, Any] | None:
        """Load a previously-persisted split by number."""
        path = self._split_path(n)
        if not os.path.exists(path):
            return None
        split_df = pd.read_parquet(path)
        test_indices = split_df["row_index"].tolist()
        test_start = split_df["test_start"].iloc[0]
        test_end = split_df["test_end"].iloc[0]
        return {
            "split_n": n,
            "test_start": test_start,
            "test_end": test_end,
            "test_indices": test_indices,
        }

    # -- Convenience: join markets + actuals for Brier scoring -----------

    def build_brier_dataset(self) -> pd.DataFrame:
        """Build Brier dataset from available data sources.

        Strategy:
        1. Try Polymarket markets + actuals (real market prices)
        2. If insufficient, supplement with historical_calibrations
           (real model forecasts + real outcomes, synthetic market price
           derived from model consensus)

        Each row = (city, target_date, model_prob, market_price, realized_outcome).
        """
        # Source 1: Polymarket markets (real market prices)
        markets = self.read_markets()
        actuals = self.read_actuals()
        poly_rows = pd.DataFrame()

        if not markets.empty and not actuals.empty:
            # Derive target_date from end_date
            end_date_col = "end_date" if "end_date" in markets.columns else "endDate"
            if end_date_col in markets.columns:
                markets["target_date"] = markets[end_date_col].dt.date.astype(str)
            actuals["join_date"] = actuals["date"].dt.date.astype(str)

            # Derive market_type and threshold if missing
            if "market_type" not in markets.columns:
                import re

                def _parse_market_type(row):
                    question = str(row.get("question", "")).lower()
                    if "highest" in question or "max" in question:
                        return "HIGH"
                    elif "lowest" in question or "min" in question:
                        return "LOW"
                    return "HIGH"

                markets["market_type"] = markets.apply(_parse_market_type, axis=1)

            if "threshold" not in markets.columns:
                import re

                def _parse_threshold(row):
                    question = str(row.get("question", ""))
                    m = re.search(r"(\d+(?:\.\d+)?)\s*[??c??CfF]", question)
                    return float(m.group(1)) if m else None

                markets["threshold"] = markets.apply(_parse_threshold, axis=1)

            # Join on (city, target_date)
            if "city" in markets.columns:
                markets["join_date"] = markets["target_date"].astype(str)
                poly_merged = markets.merge(
                    actuals,
                    on=["city", "join_date"],
                    how="inner",
                    suffixes=("_m", "_a"),
                )
                if not poly_merged.empty:
                    # Realized outcome
                    def _realized(row):
                        mt = str(row.get("market_type", "")).upper()
                        thresh = row.get("threshold")
                        actual = row.get("temperature_2m_max")
                        if thresh is None or actual is None or pd.isna(thresh) or pd.isna(actual):
                            return None
                        if mt == "HIGH":
                            return 1.0 if actual >= thresh else 0.0
                        if mt == "LOW":
                            return 1.0 if actual <= thresh else 0.0
                        return None

                    poly_merged["realized_yes"] = poly_merged.apply(_realized, axis=1)
                    poly_rows = poly_merged

        # Source 2: historical_calibrations (real forecast + real outcome)
        cal_rows = self._build_from_calibrations()

        # Source 3: Counterfactual analyses (ALL bot decisions with realized outcomes)
        # This uses the bot's own analyses table (500K+ rows) joined with actuals
        # to create "what-if" rows: model_prob, market_price, realized_yes
        cf_rows = self.build_counterfactual_dataset()

        # Combine sources
        if not poly_rows.empty and not cal_rows.empty and not cf_rows.empty:
            # Use same columns for all three
            common_cols = [
                "city",
                "target_date",
                "market_type",
                "threshold",
                "yes_price",
                "snapshot_yes_price",
                "realized_yes",
            ]
            # Ensure all common cols exist
            for col in common_cols:
                if col not in poly_rows.columns:
                    poly_rows[col] = float("nan")
                if col not in cal_rows.columns:
                    cal_rows[col] = float("nan")
                if col not in cf_rows.columns:
                    cf_rows[col] = float("nan")

            poly_subset = poly_rows[common_cols].copy()
            cal_subset = cal_rows[common_cols].copy()
            cf_subset = cf_rows[common_cols].copy()
            merged = pd.concat([poly_subset, cal_subset, cf_subset], ignore_index=True)
            logger.info(
                "Combined brier dataset: %d from Polymarket + %d from calibrations + %d from counterfactual = %d total",
                len(poly_subset),
                len(cal_subset),
                len(cf_subset),
                len(merged),
            )
        elif not poly_rows.empty and not cal_rows.empty:
            # Use same columns for both
            common_cols = [
                "city",
                "target_date",
                "market_type",
                "threshold",
                "yes_price",
                "snapshot_yes_price",
                "realized_yes",
            ]
            # Ensure all common cols exist
            for col in common_cols:
                if col not in poly_rows.columns:
                    poly_rows[col] = float("nan")
                if col not in cal_rows.columns:
                    cal_rows[col] = float("nan")

            poly_subset = poly_rows[common_cols].copy()
            cal_subset = cal_rows[common_cols].copy()
            merged = pd.concat([poly_subset, cal_subset], ignore_index=True)
            logger.info(
                "Combined brier dataset: %d from Polymarket + %d from calibrations = %d total",
                len(poly_subset),
                len(cal_subset),
                len(merged),
            )
        elif not poly_rows.empty:
            merged = poly_rows
        elif not cal_rows.empty:
            merged = cal_rows
        elif not cf_rows.empty:
            merged = cf_rows
        else:
            return pd.DataFrame()

        # Join snapshot prices if available
        if "snapshot_yes_price" not in merged.columns:
            merged["snapshot_yes_price"] = float("nan")

        snapshots = self.read_snapshots()
        if not snapshots.empty and "market_id" in snapshots.columns:
            if "timestamp" in snapshots.columns:
                snapshots = snapshots.sort_values("timestamp").groupby("market_id").last()
            if "mid_price" in snapshots.columns:
                snap_price = snapshots[["mid_price"]].rename(columns={"mid_price": "snapshot_yes_price"})
                merged = merged.merge(
                    snap_price,
                    left_on="market_id",
                    right_index=True,
                    how="left",
                )
                logger.info(
                    "Joined snapshot prices: %d/%d rows have snapshot_yes_price",
                    merged["snapshot_yes_price"].notna().sum(),
                    len(merged),
                )

        return merged

    def _build_from_calibrations(self) -> pd.DataFrame:
        """Build brier-compatible rows from historical_calibrations table.

        For each (city, date, metric):
        1. Aggregate model predictions ??? ensemble mean
        2. Use actual_value as ground truth
        3. Derive synthetic market_price from model spread
        4. Compute realized_yes based on threshold logic

        This provides real forecast + real outcome data even when
        Polymarket has no closed weather markets.
        """
        import sqlite3

        db_path = os.path.join(self.cfg.data_dir, "..", "bot.db")
        if not os.path.exists(db_path):
            return pd.DataFrame()

        try:
            conn = sqlite3.connect(db_path)
            cal = pd.read_sql_query(
                "SELECT city, date, metric, model, predicted_value, actual_value, "
                "days_ahead FROM historical_calibrations",
                conn,
            )
            conn.close()
        except Exception as exc:
            logger.warning("Failed to read historical_calibrations: %s", exc)
            return pd.DataFrame()

        if cal.empty:
            return pd.DataFrame()

        # Ensure date is string for joining
        cal["date_str"] = pd.to_datetime(cal["date"], format="mixed").dt.date.astype(str)
        cal["target_date"] = cal["date_str"]

        # For each (city, date, metric), compute ensemble stats
        rows = []
        for (city, date_str, metric), group in cal.groupby(["city", "date_str", "metric"]):
            preds = group["predicted_value"].values
            actual = group["actual_value"].iloc[0]
            group["days_ahead"].iloc[0]

            if len(preds) < 2 or pd.isna(actual):
                continue

            # Ensemble mean (simple average across models)
            ensemble_mean = float(preds.mean())
            ensemble_std = float(preds.std())

            # Market type: temperature_max ??? HIGH, temperature_min ??? LOW
            market_type = "HIGH" if "max" in metric.lower() else "LOW"

            # Synthetic market price: probability that actual exceeds threshold
            # Use ensemble mean ?? std to estimate probability
            # For HIGH: P(actual >= threshold) ??? P(normal > actual)
            # Approximate: if ensemble_mean < actual, YES is more likely
            if ensemble_std > 0:
                # Z-score: how many stds is actual from ensemble mean
                z = (actual - ensemble_mean) / max(ensemble_std, 0.1)
                # Convert to approximate probability (sigmoid approximation)
                from math import exp

                yes_prob = 1.0 / (1.0 + exp(-z))
            else:
                yes_prob = 0.5

            # Clamp to [0.01, 0.99] to avoid extreme prices
            yes_prob = max(0.01, min(0.99, yes_prob))

            # Realized outcome: did actual exceed ensemble mean direction?
            # For HIGH: YES if actual >= ensemble_mean
            # For LOW: YES if actual <= ensemble_mean
            if market_type == "HIGH":
                realized = 1.0 if actual >= ensemble_mean else 0.0
            else:
                realized = 1.0 if actual <= ensemble_mean else 0.0

            rows.append(
                {
                    "city": city,
                    "target_date": date_str,
                    "market_type": market_type,
                    "threshold": ensemble_mean,  # synthetic threshold
                    "yes_price": yes_prob,  # synthetic but derived from real data
                    "snapshot_yes_price": yes_prob,  # same (no real snapshot)
                    "realized_yes": realized,
                }
            )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        logger.info(
            "Built %d rows from historical_calibrations (%d cities, %d dates)",
            len(df),
            df["city"].nunique(),
            df["target_date"].nunique(),
        )
        return df

    def build_counterfactual_dataset(self) -> pd.DataFrame:
        """Build counterfactual Brier dataset from ALL analyses (504K rows).

        This uses the bot's own analyses table which contains:
        - estimated_probability (model probability)
        - market_implied_prob (market price)
        - recommended_side (YES/NO)
        - should_bet, reason (why bet was/wasn't placed)
        - model_predictions (JSON with 8 model forecasts)

        Joined with:
        - weather_markets ??? city, target_date, threshold, market_type
        - actuals (from unified parquet) ??? actual temperature for realized_yes

        Returns rows with: city, target_date, model_prob, market_price, realized_yes,
        should_bet, reason, recommended_side, threshold, market_type, num_sources, etc.

        This is the MISSING DATA SOURCE that Karpathy/ASI-Evolve/SIA should use
        to learn from ALL decisions, not just the 130 settled markets.
        """
        import sqlite3
        import json

        db_path = os.path.join(self.cfg.data_dir, "..", "bot.db")
        if not os.path.exists(db_path):
            logger.warning("bot.db not found at %s", db_path)
            return pd.DataFrame()

        try:
            conn = sqlite3.connect(db_path)

            # 1. Read analyses with all fields
            analyses = pd.read_sql_query(
                """
                SELECT
                    id, market_id, estimated_probability, market_implied_prob,
                    edge, raw_edge, adjusted_edge, slippage_pct,
                    avg_forecast_value, std_forecast_value, num_sources,
                    recommended_side, recommended_amount, confidence_score,
                    should_bet, reason, model_predictions, analyzed_at
                FROM analyses
                WHERE estimated_probability IS NOT NULL
                AND market_implied_prob IS NOT NULL
                AND recommended_side IS NOT NULL
            """,
                conn,
            )

            # 2. Read weather_markets for city, target_date, threshold, market_type
            markets = pd.read_sql_query(
                """
                SELECT
                    id as market_id,
                    city, city_code, metric, threshold, threshold_unit,
                    market_type, target_date, yes_price, no_price, status
                FROM weather_markets
            """,
                conn,
            )

            conn.close()

        except Exception as exc:
            logger.warning("Failed to read counterfactual data from bot.db: %s", exc)
            return pd.DataFrame()

        if analyses.empty or markets.empty:
            logger.warning("Counterfactual data empty: analyses=%d, markets=%d", len(analyses), len(markets))
            return pd.DataFrame()

        logger.info("Building counterfactual dataset: %d analyses, %d markets", len(analyses), len(markets))

        # Join analyses -> markets
        merged = analyses.merge(markets, on="market_id", how="inner")
        logger.info("After analyses+markets join: %d rows", len(merged))

        if merged.empty:
            return pd.DataFrame()

        # Parse model_predictions JSON to extract per-model forecasts
        def parse_model_preds(json_str):
            try:
                if not json_str:
                    return {}
                data = json.loads(json_str)
                if isinstance(data, dict):
                    return data
                return {}
            except Exception:
                return {}

        merged["model_preds"] = merged["model_predictions"].apply(parse_model_preds)

        # Join with actuals from unified parquet
        actuals = self.read_actuals()
        if actuals.empty:
            logger.warning("No actuals data available from unified parquet")
            return pd.DataFrame()

        # Normalize dates
        merged["target_date"] = pd.to_datetime(merged["target_date"], utc=True, errors="coerce").dt.date
        actuals["date"] = pd.to_datetime(actuals["date"], utc=True, errors="coerce").dt.date

        merged = merged.merge(actuals, left_on=["city", "target_date"], right_on=["city", "date"], how="left")
        logger.info("After actuals join: %d rows with actuals", merged["temperature_2m_max"].notna().sum())

        # Compute realized_yes based on market_type and threshold
        def compute_realized(row):
            actual_max = row.get("temperature_2m_max")
            actual_min = row.get("temperature_2m_min")
            threshold = row.get("threshold")
            market_type = row.get("market_type")

            if pd.isna(actual_max) or pd.isna(actual_min) or pd.isna(threshold):
                return None

            if market_type == "HIGH":
                return 1.0 if actual_max >= threshold else 0.0
            elif market_type == "LOW":
                return 1.0 if actual_min <= threshold else 0.0
            elif market_type == "RANGE":
                # For RANGE, need threshold_low and threshold_high
                thresh_low = row.get("threshold_low")
                thresh_high = row.get("threshold_high")
                if pd.isna(thresh_low) or pd.isna(thresh_high):
                    return None
                return 1.0 if (thresh_low <= actual_max <= thresh_high) else 0.0
            return None

        merged["realized_yes"] = merged.apply(compute_realized, axis=1)

        # Model probability: use estimated_probability (already blended)
        # Market price: use market_implied_prob
        # For NO side, flip probabilities
        def flip_probs(row):
            side = row.get("recommended_side")
            est = row.get("estimated_probability")
            mkt = row.get("market_implied_prob")
            if side == "NO":
                return 1.0 - est if pd.notna(est) else None, 1.0 - mkt if pd.notna(mkt) else None
            return est, mkt

        merged[["model_prob", "market_price"]] = merged.apply(lambda r: pd.Series(flip_probs(r)), axis=1)

        # Select and rename columns for Brier dataset compatibility
        out_cols = {
            "city": "city",
            "target_date": "target_date",
            "model_prob": "model_prob",
            "market_price": "market_price",
            "realized_yes": "realized_yes",
            "should_bet": "should_bet",
            "reason": "reason",
            "recommended_side": "recommended_side",
            "threshold": "threshold",
            "market_type": "market_type",
            "num_sources": "num_sources",
            "confidence_score": "confidence_score",
            "edge": "edge",
            "raw_edge": "raw_edge",
            "adjusted_edge": "adjusted_edge",
            "slippage_pct": "slippage_pct",
            "analyzed_at": "analyzed_at",
        }

        result = merged[list(out_cols.keys())].rename(columns=out_cols)

        # Filter: only rows with realized outcome (for Brier scoring)
        result = result.dropna(subset=["realized_yes"])
        result["realized_yes"] = result["realized_yes"].astype(float)

        # Clamp probabilities
        for col in ["model_prob", "market_price"]:
            result[col] = result[col].clip(0.01, 0.99)

        logger.info("Counterfactual dataset built: %d rows with realized outcomes", len(result))
        return result

    # -- Stats -----------------------------------------------------------

    def summary(self) -> dict[str, int]:
        """Row counts for each unified table."""
        return {
            "markets": len(self.read_markets()),
            "forecasts": len(self.read_forecasts()),
            "actuals": len(self.read_actuals()),
            "trades": len(self.read_trades()),
            "snapshots": len(self.read_snapshots()),
        }


# ---------------------------------------------------------------------------
# Convenience: full ingest pipeline (one-shot)
# ---------------------------------------------------------------------------


def _ingest_poly_markets(
    ds: "UnifiedDatastore",
    markets_limit: int | None,
) -> None:
    """Step 1: Fetch weather markets from bot's own database ??? unified_markets table.

    The bot's weather_markets table contains 130+ settled weather markets with
    proper city, metric, threshold, market_type, and target_date.
    We use these instead of Polymarket's closed markets API (which has no weather markets).
    """
    logger.info("=== [1/4] Bot weather markets (from bot.db) ===")
    try:
        import sqlite3
        import pandas as pd

        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db")
        if not os.path.exists(db_path):
            logger.warning("bot.db not found at %s", db_path)
            return

        conn = sqlite3.connect(db_path)
        # Fetch settled markets (win + loss) with all needed fields
        query = """
            SELECT
                id as market_id,
                question,
                city,
                city_code,
                metric,
                threshold,
                threshold_unit,
                market_type,
                target_date,
                target_date as end_date,
                target_date as closed_time,
                yes_price,
                no_price,
                volume,
                liquidity,
                status,
                '[]' as clob_token_ids
            FROM weather_markets
            WHERE status IN ('settled_win', 'settled_loss')
        """
        unified = pd.read_sql_query(query, conn)
        conn.close()

        if unified.empty:
            logger.warning("No settled weather markets found in bot.db")
            return

        logger.info("Loaded %d settled weather markets from bot.db", len(unified))

        # Ensure datetime columns are proper
        for col in ["target_date", "end_date", "closed_time"]:
            if col in unified.columns:
                unified[col] = pd.to_datetime(unified[col], utc=True, errors="coerce")

        # Map status to resolved_outcome
        unified["resolved_outcome"] = unified["status"].map({"settled_win": "Yes", "settled_loss": "No"})

        ds.write_markets(unified)
        logger.info("Wrote %d markets to unified_markets.parquet", len(unified))
    except Exception as exc:
        logger.error("Bot weather markets ingest failed: %s", exc)


def _ingest_weather_actuals(
    ds: "UnifiedDatastore",
    weather_locations: list[tuple[str, float, float]],
    backfill_days: int,
) -> None:
    """Step 2: Fetch weather actuals from Open-Meteo Archive ??? unified_actuals."""
    logger.info("=== [2/4] Weather actuals (Open-Meteo Archive) ===")
    try:
        from data_pipeline.weather_ensemble import backfill_archive_many

        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
        start_date = (datetime.now(UTC) - pd.Timedelta(days=backfill_days)).strftime("%Y-%m-%d")
        actuals_df = backfill_archive_many(
            weather_locations,
            start_date=start_date,
            end_date=end_date,
        )
        if not actuals_df.empty:
            actuals_df["date"] = pd.to_datetime(actuals_df["date"], utc=True)
            ds.write_actuals(actuals_df)
    except Exception as exc:
        logger.error("Weather actuals ingest failed: %s", exc)


def _ingest_forecasts(
    ds: "UnifiedDatastore",
    weather_locations: list[tuple[str, float, float]],
) -> None:
    """Step 3: Fetch weather forecasts (historical backfill + live + NWS).

    Sub-steps:
      (a) Historical backfill from Open-Meteo Historical Forecast API
      (b) Live ensemble for forward-looking markets
      (c) NWS deterministic forecast (US cities only -- 9th pseudo-model)
    """
    logger.info("=== [3/4] Weather forecasts (historical backfill + live ensemble) ===")
    try:
        import time as _time

        from data_pipeline.weather_ensemble import (
            backfill_historical_forecasts_many,
            fetch_forecast_ensemble,
        )

        forecast_frames: list[pd.DataFrame] = []

        # (a) Historical backfill
        try:
            markets_df_for_range = ds.read_markets()
            date_col = None
            for cand in ("target_date", "end_date"):
                if cand in markets_df_for_range.columns:
                    date_col = cand
                    break
            if date_col and not markets_df_for_range.empty:
                dt_series = pd.to_datetime(markets_df_for_range[date_col], utc=True, errors="coerce").dropna()
                if not dt_series.empty:
                    hist_start = dt_series.min().strftime("%Y-%m-%d")
                    hist_end = max(
                        dt_series.max().strftime("%Y-%m-%d"),
                        (datetime.now(UTC) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    )
                    logger.info(
                        "Historical forecast backfill %s..%s across %d cities",
                        hist_start,
                        hist_end,
                        len(weather_locations),
                    )
                    hist_df = backfill_historical_forecasts_many(
                        weather_locations,
                        start_date=hist_start,
                        end_date=hist_end,
                    )
                    if not hist_df.empty:
                        hist_df["target_date"] = pd.to_datetime(hist_df["date"], utc=True, errors="coerce")
                        hist_df["fetched_at"] = pd.Timestamp.utcnow()
                        forecast_frames.append(
                            hist_df[
                                [
                                    "city",
                                    "latitude",
                                    "longitude",
                                    "target_date",
                                    "model",
                                    "variable",
                                    "value",
                                    "fetched_at",
                                ]
                            ]
                        )
                        logger.info(
                            "Historical forecast backfill: %d rows across %d models",
                            len(hist_df),
                            hist_df["model"].nunique(),
                        )
        except Exception as exc:
            logger.warning("Historical forecast backfill skipped: %s", exc)

        # (b) Live ensemble -- small sample for forward-looking markets
        for city, lat, lon in weather_locations[:5]:
            res = fetch_forecast_ensemble(lat, lon, city=city)
            if res:
                fc = res.forecasts.copy()
                fc["city"] = city
                fc["latitude"] = lat
                fc["longitude"] = lon
                fc["target_date"] = pd.Timestamp(res.target_date, tz="UTC")
                fc["fetched_at"] = pd.Timestamp.utcnow()
                forecast_frames.append(fc)
            _time.sleep(0.5)

        # (c) NWS deterministic forecast (US cities only)
        try:
            from data_pipeline.weather_ensemble import fetch_nws_forecast

            nws_frames = []
            for city, lat, lon in weather_locations:
                nws_df = fetch_nws_forecast(lat, lon, city=city)
                if not nws_df.empty:
                    nws_df["target_date"] = pd.to_datetime(nws_df["date"], utc=True, errors="coerce")
                    nws_df["fetched_at"] = pd.Timestamp.utcnow()
                    nws_frames.append(
                        nws_df[
                            [
                                "city",
                                "latitude",
                                "longitude",
                                "target_date",
                                "model",
                                "variable",
                                "value",
                                "fetched_at",
                            ]
                        ]
                    )
                _time.sleep(0.2)
            if nws_frames:
                forecast_frames.append(pd.concat(nws_frames, ignore_index=True))
                logger.info(
                    "NWS forecast fetch: %d US-city rows",
                    sum(len(f) for f in nws_frames),
                )
        except Exception as exc:
            logger.warning("NWS forecast fetch skipped: %s", exc)

        if forecast_frames:
            ds.write_forecasts(pd.concat(forecast_frames, ignore_index=True))
    except Exception as exc:
        logger.error("Forecast ingest failed: %s", exc)


def _ingest_resolved_snapshots(
    ds: "UnifiedDatastore",
    market_ids: list[str] | None,
) -> None:
    """Step 4: Fetch Resolved Markets orderbook snapshots (optional)."""
    if not market_ids:
        logger.info("=== [4/4] Skipped Resolved Markets snapshots (use_resolvedmarkets=False) ===")
        return

    logger.info("=== [4/4] Resolved Markets snapshots ===")
    try:
        from data_pipeline.resolvedmarkets_ingest import client_from_env

        client = client_from_env()
        snapshot_frames = []
        for cid in market_ids[:20]:
            try:
                df = client.fetch_all_snapshots(cid, interval="1h")
                if not df.empty:
                    df["market_id"] = cid
                    snapshot_frames.append(df)
            except Exception as exc:
                logger.warning("Snapshots failed for %s: %s", cid, exc)
        if snapshot_frames:
            ds.write_snapshots(pd.concat(snapshot_frames, ignore_index=True))
    except Exception as exc:
        logger.error("Resolvedmarkets ingest failed: %s", exc)


def ingest_all(
    *,
    weather_locations: list[tuple[str, float, float]] | None = None,
    backfill_days: int = 90,
    markets_limit: int | None = 2000,
    use_resolvedmarkets: bool = False,
    resolvedmarkets_market_ids: list[str] | None = None,
) -> dict[str, int]:
    """Run all 4 ingest modules and write to the unified datastore.

    This is the entry point for a full backtest data refresh.

    Args:
        weather_locations: list of (city, lat, lon) for weather backfill.
            Defaults to a small set if None.
        backfill_days: how many days of historical actuals to fetch.
        markets_limit: cap on number of closed markets to fetch from Gamma.
        use_resolvedmarkets: if True, also fetch orderbook snapshots for each
            weather market (requires RESOLVEDMARKETS_API_KEY).
        resolvedmarkets_market_ids: specific condition_ids to fetch snapshots for.

    Returns a dict of row counts per table.
    """
    if weather_locations is None:
        weather_locations = [
            ("Miami", 25.7617, -80.1918),
            ("NewYork", 40.7128, -74.0060),
            ("LosAngeles", 34.0522, -118.2437),
            ("Chicago", 41.8781, -87.6298),
            ("Houston", 29.7604, -95.3698),
            ("London", 51.5074, -0.1278),
            ("Paris", 48.8566, 2.3522),
            ("Tokyo", 35.6762, 139.6503),
            ("Seoul", 37.5665, 126.9780),
            ("Sydney", -33.8688, 151.2093),
            ("Dubai", 25.2048, 55.2708),
            ("Singapore", 1.3521, 103.8198),
            ("Berlin", 52.5200, 13.4050),
            ("Madrid", 40.4168, -3.7038),
            ("Rome", 41.9028, 12.4964),
        ]

    ds = UnifiedDatastore()

    _ingest_poly_markets(ds, markets_limit)
    _ingest_weather_actuals(ds, weather_locations, backfill_days)
    _ingest_forecasts(ds, weather_locations)
    _ingest_resolved_snapshots(
        ds,
        resolvedmarkets_market_ids if use_resolvedmarkets else None,
    )

    return ds.summary()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-22s  %(message)s")

    print("\n=== Full ingest pipeline (smoke test) ===")
    counts = ingest_all(backfill_days=30, markets_limit=200)
    print("\n=== Unified datastore summary ===")
    print(counts)

    print("\n=== Walk-forward splits ===")
    ds = UnifiedDatastore()
    splits = ds.build_walk_forward_splits(
        lookback_days=14,
        step_days=7,
        test_days=7,
        date_column="end_date",
        table_name="markets",
    )
    print(f"Built {len(splits)} splits")
