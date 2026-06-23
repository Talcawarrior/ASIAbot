"""Tests for autoresearch/eval_harness.py — verify the harness is honest.

These tests confirm the harness no longer leaks ground-truth information
into the market price (the bug that previously inflated the reported
Sharpe/ROI numbers in the README).
"""

import io

# eval_harness.py is a top-level script in autoresearch/, not a package.
# We add the autoresearch directory to sys.path so we can import it.
import os
import random
import re
import sys
from contextlib import redirect_stdout

_AUTORESEARCH_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "autoresearch")
)
if _AUTORESEARCH_DIR not in sys.path:
    sys.path.insert(0, _AUTORESEARCH_DIR)

import eval_harness  # noqa: E402  (import after sys.path tweak)


def _run_harness(seed: int = 101):
    """Run the harness with a specific RNG seed and return parsed metrics."""
    random.seed(seed)
    buf = io.StringIO()
    with redirect_stdout(buf):
        eval_harness.run_evaluation_harness(num_scenarios=1000)
    out = buf.getvalue()

    metrics = {}
    for line in out.splitlines():
        m = re.match(r"^(\w+):\s*(-?\d+\.?\d*)$", line.strip())
        if m:
            metrics[m.group(1)] = float(m.group(2))
    return metrics


class TestEvalHarnessHonesty:
    def test_market_price_does_not_leak_ground_truth(self):
        """The harness must NOT build the market price from the ground-truth
        outcome. Verify by checking that the source code of
        `run_evaluation_harness` does not branch on `ground_truth_yes`
        when computing `market_yes_price`.
        """
        import inspect

        src = inspect.getsource(eval_harness.run_evaluation_harness)
        # Find the market price block.
        assert "market_yes_price" in src, "market_yes_price missing from harness source"
        # The block must NOT contain a branch on ground_truth_yes.
        # Specifically, the pattern `if ground_truth_yes:` followed by
        # `market_yes_price +=` is forbidden.
        forbidden_pattern = re.compile(
            r"if\s+ground_truth_yes\s*:.*?market_yes_price\s*[\+\-]?=",
            re.DOTALL,
        )
        assert not forbidden_pattern.search(src), (
            "eval_harness.py appears to branch on ground_truth_yes when "
            "building market_yes_price — this is the leak we removed."
        )

    def test_harness_runs_to_completion(self):
        metrics = _run_harness(seed=101)
        assert "Sharpe_Ratio" in metrics
        assert "Net_ROI_Pct" in metrics
        assert "Total_Trades" in metrics
        assert "Win_Rate" in metrics
        assert metrics["Total_Trades"] > 0

    def test_harness_is_deterministic_under_same_seed(self):
        """With the same seed, two runs must produce identical metrics."""
        m1 = _run_harness(seed=101)
        m2 = _run_harness(seed=101)
        assert m1 == m2

    def test_sharpe_is_per_trade_not_inflated(self):
        """The previous version multiplied the per-trade Sharpe by
        sqrt(min(total_trades, 252)) which inflated the number to ~2.0.
        The honest per-trade Sharpe should be < 1.0 for a naive strategy
        against a fairly-priced market.
        """
        metrics = _run_harness(seed=101)
        # Per-trade Sharpe for a strategy that is roughly fair should
        # be in the [-0.5, 0.5] range. If we see ≥ 1.0, we are back to
        # the inflated-calculation bug.
        assert metrics["Sharpe_Ratio"] < 1.0, (
            f"Sharpe {metrics['Sharpe_Ratio']} > 1.0 — harness is inflating "
            "the per-trade Sharpe again."
        )

    def test_roi_does_not_imply_certain_profit(self):
        """If the harness were leaking ground truth, the bot would print
        ROI > 70% (as the original README claimed). With an honest market
        price, ROI should be much more modest.
        """
        metrics = _run_harness(seed=101)
        # 60% is a generous upper bound; the original buggy version
        # reported ~74%. An honest harness against a fairly-priced market
        # should report well below 60% (typically single digits to low
        # tens, depending on the inefficiency noise).
        assert metrics["Net_ROI_Pct"] < 60.0, (
            f"ROI {metrics['Net_ROI_Pct']}% — harness may still be leaking "
            "ground truth into the market price."
        )
