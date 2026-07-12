"""Smoke test for the SIA hourly layer (asi_engine/sia_hourly.py).

Verifies:
  1. Module imports cleanly.
  2. MetaAgent.decide() returns at least one action (weight_mutation only).
  3. TargetAgent.mutate_weights() returns a valid Hypothesis.
  3. FeedbackAgent.evaluate_weight_mutation() works.
  4. run_sia_hourly() runs end-to-end without raising.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asi_engine.karpathy_weekly import (  # noqa: E402
    Hypothesis,
    _uniform_weights,
)
from asi_engine.sia_hourly import (  # noqa: E402
    FeedbackAgent,
    MetaAgent,
    SIAState,
    TargetAgent,
    run_sia_hourly,
)


def test_meta_agent_returns_at_least_one_action():
    meta = MetaAgent(use_llm=False)
    state = SIAState(
        parent_hypothesis=Hypothesis(
            description="test",
            model_weights=_uniform_weights(),
            min_edge=0.05,
            kelly_fraction=0.15,
            max_bet_pct=0.05,
        ),
        parent_stats={"sharpe": 0.0, "brier_score": 0.30, "total_trades": 5},
    )
    actions = meta.decide(state)
    assert len(actions) >= 1
    # Only weight_mutation should be returned (harness_patch removed)
    assert all(a == "weight_mutation" for a in actions)


def test_meta_agent_suggests_weight_mutation_when_sharpe_low():
    meta = MetaAgent(use_llm=False)
    state = SIAState(
        parent_hypothesis=Hypothesis(
            description="test",
            model_weights=_uniform_weights(),
            min_edge=0.05,
            kelly_fraction=0.15,
            max_bet_pct=0.05,
        ),
        parent_stats={"sharpe": 0.2, "brier_score": 0.20, "total_trades": 100},
    )
    actions = meta.decide(state)
    assert "weight_mutation" in actions


def test_meta_agent_suggests_weight_mutation_when_few_trades():
    meta = MetaAgent(use_llm=False)
    state = SIAState(
        parent_hypothesis=Hypothesis(
            description="test",
            model_weights=_uniform_weights(),
            min_edge=0.05,
            kelly_fraction=0.15,
            max_bet_pct=0.05,
        ),
        parent_stats={"sharpe": 1.0, "brier_score": 0.20, "total_trades": 5},
    )
    actions = meta.decide(state)
    assert "weight_mutation" in actions


def test_target_agent_mutate_weights_returns_valid_hypothesis():
    target = TargetAgent(use_llm=False, seed=42)
    parent = Hypothesis(
        description="parent",
        model_weights=_uniform_weights(),
        min_edge=0.05,
        kelly_fraction=0.15,
        max_bet_pct=0.05,
    )
    child = target.mutate_weights(parent)
    assert isinstance(child, Hypothesis)
    assert abs(sum(child.model_weights.values()) - 1.0) < 1e-3
    assert child.source == "sia_weight_mutation"
    # min_edge, kelly, blend should be nudged
    assert 0.01 <= child.min_edge <= 0.15
    assert 0.05 <= child.kelly_fraction <= 0.30
    assert 0.35 <= child.blend_weight <= 0.50


def test_feedback_agent_evaluate_weight_mutation():
    fb = FeedbackAgent(pd.DataFrame(), [])
    parent = Hypothesis(
        description="parent",
        model_weights=_uniform_weights(),
        min_edge=0.05,
        kelly_fraction=0.15,
        max_bet_pct=0.05,
    )
    stats = fb.evaluate_weight_mutation(parent)
    assert "sharpe" in stats
    assert "roi_pct" in stats
    assert "win_rate" in stats
    assert "total_trades" in stats
    assert "brier_score" in stats
    assert "total_pnl" in stats
    assert "total_staked" in stats


def test_run_sia_hourly_smoke():
    """End-to-end smoke test — should not raise even if data is empty."""
    summary = run_sia_hourly(use_llm=False, seed=42)
    # Either it ran or returned early with error
    assert "cycles_run" in summary or "error" in summary
    if summary.get("error"):
        assert summary["cycles_run"] == 0
        return
    assert summary["cycles_run"] == 1
    assert "actions_taken" in summary
    assert "best_hypothesis" in summary
    assert "best_stats" in summary
    # Best hypothesis weights must be normalised
    bw = summary["best_hypothesis"]["model_weights"]
    assert abs(sum(bw.values()) - 1.0) < 1e-3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
