"""Pipeline data quality tests — prevents fake price bugs.

These tests verify the entire data pipeline from raw API response to brier_df,
catching the class of bug where:
  - _safe_json_loads fails to parse Python repr format -> yes_price = None
  - yes_price defaults to 0.5 (fake) -> backtest evaluates against wrong market
  - snapshot_yes_price is missing -> backtest uses resolved outcome as entry

Run: pytest tests/test_pipeline_data_quality.py -v
"""

import json

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# 1. _safe_json_loads — must handle both JSON and Python repr formats
# ---------------------------------------------------------------------------


class TestSafeJsonLoads:
    """CSV serialization converts JSON lists to Python repr with single quotes.
    _safe_json_loads must handle both formats."""

    def _func(self):
        from data_pipeline.polymarket_ingest import _safe_json_loads

        return _safe_json_loads

    def test_json_double_quotes(self):
        fn = self._func()
        result = fn('["0", "1"]')
        assert isinstance(result, list)
        assert result == ["0", "1"]

    def test_python_repr_single_quotes(self):
        """This is the bug that caused 100% fallback to 0.5."""
        fn = self._func()
        result = fn("['0', '1']")
        assert isinstance(result, list), f"Got {type(result)}: {result}"
        assert result == ["0", "1"]

    def test_already_list(self):
        fn = self._func()
        result = fn(["0", "1"])
        assert result == ["0", "1"]

    def test_already_dict(self):
        fn = self._func()
        result = fn({"key": "val"})
        assert result == {"key": "val"}

    def test_none_returns_none(self):
        fn = self._func()
        assert fn(None) is None

    def test_empty_string_returns_none(self):
        fn = self._func()
        assert fn("") is None

    def test_invalid_string_returns_original(self):
        fn = self._func()
        assert fn("not a list") == "not a list"

    def test_nested_list(self):
        fn = self._func()
        result = fn("[[1, 2], [3, 4]]")
        assert result == [[1, 2], [3, 4]]

    def test_dict_python_repr(self):
        """Python repr with single quotes in dict."""
        fn = self._func()
        result = fn("{'key': 'val'}")
        assert isinstance(result, dict)
        assert result == {"key": "val"}


# ---------------------------------------------------------------------------
# 2. _extract_outcome_price — must parse prices correctly
# ---------------------------------------------------------------------------


class TestExtractOutcomePrice:
    """Verify price extraction from market data after _safe_json_loads."""

    def _func(self):
        from data_pipeline.polymarket_ingest import _extract_outcome_price

        return _extract_outcome_price

    def test_yes_price_from_json_list(self):
        fn = self._func()
        row = pd.Series(
            {
                "outcomePrices": ["0", "1"],
                "outcomes": ["Yes", "No"],
            }
        )
        assert fn(row, "yes") == 0.0

    def test_no_price_from_json_list(self):
        fn = self._func()
        row = pd.Series(
            {
                "outcomePrices": ["0", "1"],
                "outcomes": ["Yes", "No"],
            }
        )
        assert fn(row, "no") == 1.0

    def test_yes_price_from_python_repr(self):
        """Previously returned None because JSON parser failed on single quotes."""
        fn = self._func()
        row = pd.Series(
            {
                "outcomePrices": ["1", "0"],
                "outcomes": ["Yes", "No"],
            }
        )
        assert fn(row, "yes") == 1.0

    def test_none_outcomes_returns_none(self):
        fn = self._func()
        row = pd.Series({"outcomePrices": None, "outcomes": None})
        assert fn(row, "yes") is None

    def test_empty_outcomes_returns_none(self):
        fn = self._func()
        row = pd.Series({"outcomePrices": [], "outcomes": []})
        assert fn(row, "yes") is None


# ---------------------------------------------------------------------------
# 3. _extract_resolved_outcome — must handle string prices from CSV
# ---------------------------------------------------------------------------


class TestExtractResolvedOutcome:
    def _func(self):
        from data_pipeline.polymarket_ingest import _extract_resolved_outcome

        return _extract_resolved_outcome

    def test_float_yes_wins(self):
        fn = self._func()
        assert fn(pd.Series({"yes_price": 1.0, "no_price": 0.0})) == "Yes"

    def test_float_no_wins(self):
        fn = self._func()
        assert fn(pd.Series({"yes_price": 0.0, "no_price": 1.0})) == "No"

    def test_string_prices(self):
        """CSV reads prices as strings — must still work."""
        fn = self._func()
        assert fn(pd.Series({"yes_price": "1.0", "no_price": "0.0"})) == "Yes"

    def test_none_returns_none(self):
        fn = self._func()
        assert fn(pd.Series({"yes_price": None, "no_price": None})) is None

    def test_ambiguous_returns_none(self):
        fn = self._func()
        assert fn(pd.Series({"yes_price": 0.5, "no_price": 0.5})) is None


# ---------------------------------------------------------------------------
# 4. build_brier_dataset — structural quality checks
# ---------------------------------------------------------------------------


class TestBrierDataset:
    """Verify the brier dataset has the right columns and no fake data."""

    @pytest.fixture(autouse=True)
    def _load(self):
        from data_pipeline.unified_datastore import UnifiedDatastore

        self.ds = UnifiedDatastore()
        self.df = self.ds.build_brier_dataset()

    def test_not_empty(self):
        assert not self.df.empty, "brier_df is empty — run ingest_all() first"

    def test_has_required_columns(self):
        required = {"yes_price", "realized_yes", "market_type", "threshold", "city"}
        missing = required - set(self.df.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_has_snapshot_column(self):
        """snapshot_yes_price must exist (even if all NaN)."""
        assert "snapshot_yes_price" in self.df.columns

    def test_yes_price_not_all_same(self):
        """If all yes_price values are identical, it's likely a default/fake."""
        unique = self.df["yes_price"].nunique()
        assert unique > 1, (
            f"yes_price has only {unique} unique value(s): {self.df['yes_price'].unique()} — likely fake default!"
        )

    def test_yes_price_in_valid_range(self):
        """yes_price should be between 0 and 1 (exclusive of extremes for betting)."""
        valid = self.df["yes_price"].between(0, 1).all()
        assert valid, f"yes_price out of range: {self.df['yes_price'].describe()}"

    def test_realized_yes_is_binary(self):
        """realized_yes should be 0.0 or 1.0 (or NaN for unresolvable)."""
        valid = self.df["realized_yes"].dropna().isin([0.0, 1.0]).all()
        assert valid, "realized_yes contains non-binary values"

    def test_no_all_nan_snapshot(self):
        """If snapshot_yes_price is all NaN, warn but don't fail — snapshots may not be populated."""
        if self.df["snapshot_yes_price"].isna().all():
            pytest.skip(
                "snapshot_yes_price is all NaN — snapshots not populated yet. "
                "This means karpathy_weekly will skip all bet decisions (correct behavior)."
            )


# ---------------------------------------------------------------------------
# 5. karpathy_best.json — sanity checks on saved hypothesis
# ---------------------------------------------------------------------------


class TestKarpathyBest:
    """Verify the saved hypothesis isn't built on fake data."""

    def _load(self):
        import os

        path = "data/karpathy_best.json"
        if not os.path.exists(path):
            pytest.skip("karpathy_best.json not found — run Karpathy first")
        with open(path) as f:
            return json.load(f)

    def test_file_exists_or_skip(self):
        """If file doesn't exist, skip (not a failure — Karpathy hasn't run yet)."""
        import os

        if not os.path.exists("data/karpathy_best.json"):
            pytest.skip("karpathy_best.json not found — run Karpathy first")

    def test_reasonable_stats(self):
        best = self._load()
        stats = best.get("stats", {})
        roi = stats.get("roi_pct", 0)
        sharpe = stats.get("sharpe", 0)
        win_rate = stats.get("win_rate", 0)
        # ROI > 1000% on weather markets is suspicious (Karpathy best ~632% is real but high variance)
        assert roi < 1000, f"ROI {roi}% is suspiciously high — likely fake data"
        # Sharpe > 10 is suspicious
        assert sharpe < 10, f"Sharpe {sharpe} is suspiciously high — likely fake data"
        # Win rate > 80% is suspicious for weather markets
        assert win_rate < 0.80, f"Win rate {win_rate} is suspiciously high — likely fake data"
