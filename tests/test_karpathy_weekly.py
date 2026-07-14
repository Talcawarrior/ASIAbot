"""Smoke test for the Karpathy weekly layer (asi_engine/karpathy_weekly.py).

Verifies:
  1. Module imports cleanly.
  2. evaluate_hypothesis_oos() runs against a tiny synthetic Brier dataset
     and returns the expected stat keys.
  3. generate_hypothesis() returns a valid Hypothesis with normalised weights.
  4. run_karpathy_weekly() with rounds=1 runs end-to-end against whatever
     data is in data/unified/ (may return early if Brier dataset is empty —
     that's acceptable for CI; the test just checks no exceptions are raised).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asi_engine.karpathy_weekly import (  # noqa: E402
    DEFAULT_MODELS,
    Hypothesis,
    _uniform_weights,
    evaluate_hypothesis_oos,
    generate_hypothesis,
    run_karpathy_weekly,
)


def _make_synthetic_brier_df(n_rows: int = 20) -> pd.DataFrame:
    """Build a tiny synthetic Brier dataset for OOS evaluation testing."""
    rows = []
    for i in range(n_rows):
        row = {
            "market_id": f"m{i}",
            "city": "Miami",
            "market_type": "HIGH" if i % 2 == 0 else "LOW",
            "threshold": 30.0 + (i % 5),
            "target_date": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=i),
            "realized_yes": float(i % 3 != 0),  # 2/3 YES, 1/3 NO
            "snapshot_yes_price": 0.55 + (i % 5) * 0.02,
            "days_ahead": 1 + (i % 4),
        }
        # Per-model YES probabilities (around 0.5-0.7)
        for m in DEFAULT_MODELS:
            row[f"prob_{m}"] = max(0.01, min(0.99, 0.6 + (i % 7 - 3) * 0.05))
        rows.append(row)
    return pd.DataFrame(rows)


def test_hypothesis_weights_are_normalised():
    hyp = generate_hypothesis(0)
    assert isinstance(hyp, Hypothesis)
    assert abs(sum(hyp.model_weights.values()) - 1.0) < 1e-3, "weights must sum to 1.0"
    assert 0.02 <= hyp.min_edge <= 0.15
    assert 0.05 <= hyp.kelly_fraction <= 0.30
    assert all(m in hyp.model_weights for m in DEFAULT_MODELS)


def test_evaluate_hypothesis_oos_returns_expected_keys():
    df = _make_synthetic_brier_df(20)
    test_indices = list(range(10, 20))
    hyp = generate_hypothesis(0)
    stats = evaluate_hypothesis_oos(df, test_indices, hyp)
    expected_keys = {
        "sharpe",
        "roi_pct",
        "win_rate",
        "total_trades",
        "brier_score",
        "total_pnl",
        "total_staked",
    }
    assert set(stats.keys()) == expected_keys
    assert isinstance(stats["total_trades"], int)
    assert 0.0 <= stats["win_rate"] <= 1.0
    assert 0.0 <= stats["brier_score"] <= 1.0


def test_evaluate_hypothesis_oos_empty_indices():
    df = _make_synthetic_brier_df(5)
    hyp = generate_hypothesis(0)
    stats = evaluate_hypothesis_oos(df, [], hyp)
    assert stats["total_trades"] == 0
    assert stats["sharpe"] == 0.0


def test_evaluate_hypothesis_oos_no_lookahead_bias():
    """
    Regression test for look-ahead bias bug (commit 2f7ddde era).

    The bug: evaluate_hypothesis_oos used `snapshot_yes_price` (which is the
    RESOLVED outcome price, 0.0 or 1.0) as the market price for Kelly sizing
    and edge calculation. This gives the model perfect hindsight — it knows
    the outcome before betting.

    Correct behavior: use `yes_price` (pre-resolution market price) for
    Kelly sizing and edge calculation. `snapshot_yes_price` should only be
    used for Brier score calculation against the realized outcome.

    This test creates a dataset where:
    - yes_price = 0.5 (pre-resolution market price)
    - snapshot_yes_price = 1.0 (resolved outcome = YES)
    - realized_yes = 1.0 (outcome = YES)

    If the bug exists, the model sees market_price=1.0, edge = prob - 1.0
    (always negative for prob < 1.0), so it never bets → 0 trades.

    If fixed, the model sees market_price=0.5, edge = prob - 0.5
    (positive for prob > 0.5) → bets on YES → positive PnL.
    """
    df = pd.DataFrame(
        {
            "market_id": ["m1", "m2", "m3", "m4"],
            "city": ["Miami"] * 4,
            "market_type": ["HIGH"] * 4,
            "threshold": [30.0] * 4,
            "target_date": pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC"),
            "realized_yes": [1.0, 1.0, 1.0, 1.0],  # All resolved YES
            "yes_price": [0.5, 0.5, 0.5, 0.5],  # Pre-resolution market price
            "snapshot_yes_price": [1.0, 1.0, 1.0, 1.0],  # Resolved outcome (BUG SOURCE)
            "days_ahead": [1, 1, 1, 1],
        }
    )
    # Add per-model probabilities (all models predict 0.7 for YES)
    for m in DEFAULT_MODELS:
        df[f"prob_{m}"] = 0.7

    test_indices = list(range(4))
    hyp = Hypothesis(
        description="test",
        model_weights={m: 1.0 / len(DEFAULT_MODELS) for m in DEFAULT_MODELS},
        min_edge=0.05,
        kelly_fraction=0.15,
        max_bet_pct=0.05,
        blend_weight=0.5,
    )

    stats = evaluate_hypothesis_oos(df, test_indices, hyp)

    # If bug exists: 0 trades (model sees market_price=1.0, edge always negative)
    # If fixed: >0 trades (model sees market_price=0.5, edge=0.2 positive)
    assert stats["total_trades"] > 0, (
        "Look-ahead bias detected! evaluate_hypothesis_oos used snapshot_yes_price "
        "(resolved outcome) instead of yes_price (pre-resolution market price). "
        f"Got {stats['total_trades']} trades, expected >0."
    )

    # Verify positive PnL (model correctly bets on YES at 0.5, outcome is YES)
    assert stats["total_pnl"] > 0, "Expected positive PnL when betting on YES at 0.5 with outcome YES"


def test_uniform_weights():
    w = _uniform_weights()
    assert len(w) == len(DEFAULT_MODELS)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    # All equal
    assert len(set(w.values())) == 1


def test_run_karpathy_weekly_smoke():
    """End-to-end smoke test — should not raise even if data is empty."""
    # rounds=1 — minimal
    summary = run_karpathy_weekly(rounds=1, use_llm=False, seed=42)
    # Either it ran successfully or it returned early with an error
    # (Brier dataset requires upstream weather market parsing — may not be
    # populated in CI yet, which is acceptable.)
    assert "rounds_run" in summary or "error" in summary
    if summary.get("error"):
        # Early return — verify the error key is informative
        assert "rounds_run" in summary
        assert summary["rounds_run"] == 0
        return
    if "rounds_run" in summary:
        assert summary["rounds_run"] == 1
        assert "best_hypothesis" in summary
        assert "best_stats" in summary
        # Best hypothesis must have normalised weights
        bw = summary["best_hypothesis"]["model_weights"]
        assert abs(sum(bw.values()) - 1.0) < 1e-3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
