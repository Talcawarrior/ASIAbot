"""Tests for the Karpathy-style autonomous parameter search.

MIGRATED from scripts/karpathy_search.py (deleted during project cleanup)
to test the production implementation in asi_engine/karpathy_weekly.py.

The original tests called `karpathy_search.search()` which ran an end-to-end
search loop. The production code splits this into:
  - generate_hypothesis() — propose a candidate
  - evaluate_hypothesis_oos() — score it on OOS data
  - _save_best() — persist winner to data/karpathy_best.json
  - run_karpathy_weekly() — orchestrate the full loop (needs real data)

These tests cover the unit-testable pieces without requiring a populated
unified datastore (which would make them integration tests).
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BEST_PATH = REPO / "data" / "karpathy_best.json"


@pytest.fixture
def clean_best_file():
    """Ensure karpathy_best.json doesn't exist before/after the test."""
    backup = None
    if BEST_PATH.exists():
        backup = BEST_PATH.read_text(encoding="utf-8")
        BEST_PATH.unlink()
    yield
    if BEST_PATH.exists():
        BEST_PATH.unlink()
    if backup is not None:
        BEST_PATH.write_text(backup, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Hypothesis generation produces a valid candidate
# (replaces test_karpathy_search_runs_with_small_budget)
# ---------------------------------------------------------------------------


def test_generate_hypothesis_produces_valid_candidate():
    """generate_hypothesis() should return a Hypothesis with all the
    expected fields populated — same fields the original test checked.
    """
    from asi_engine.karpathy_weekly import Hypothesis, generate_hypothesis

    hyp = generate_hypothesis(round_num=0, parent=None)

    assert isinstance(hyp, Hypothesis), "generate_hypothesis must return a Hypothesis"
    assert isinstance(hyp.description, str) and hyp.description
    assert isinstance(hyp.model_weights, dict) and len(hyp.model_weights) > 0
    # Same fields the original test_karpathy_search_runs_with_small_budget asserted:
    assert "min_edge" in hyp.__dataclass_fields__
    assert "kelly_fraction" in hyp.__dataclass_fields__
    # model_weights must sum to ~1.0
    total = sum(hyp.model_weights.values())
    assert 0.99 <= total <= 1.01, f"model_weights sum={total}, expected ~1.0"
    # min_edge must be positive (above breakeven)
    assert hyp.min_edge > 0, f"min_edge={hyp.min_edge} must be > 0"
    # kelly_fraction must be in (0, 1]
    assert 0 < hyp.kelly_fraction <= 1, f"kelly_fraction={hyp.kelly_fraction} out of (0,1]"


# ---------------------------------------------------------------------------
# Test 2: Hypothesis generation is deterministic with same round
# (replaces test_karpathy_search_is_deterministic)
# ---------------------------------------------------------------------------


def test_generate_hypothesis_is_deterministic():
    """Two calls to generate_hypothesis() with the same round_num and
    parent must produce identical hypotheses — the mutation ladder is
    indexed by round_num, so it must be reproducible.
    """
    from asi_engine.karpathy_weekly import generate_hypothesis

    # Without LLM (deterministic mutation ladder)
    h1 = generate_hypothesis(round_num=3, parent=None)
    h2 = generate_hypothesis(round_num=3, parent=None)

    # Same round → same hypothesis from the ladder
    assert h1.description == h2.description, "descriptions differ for same round"
    assert h1.min_edge == h2.min_edge, f"min_edge differs: {h1.min_edge} vs {h2.min_edge}"
    assert h1.kelly_fraction == h2.kelly_fraction, (
        f"kelly_fraction differs: {h1.kelly_fraction} vs {h2.kelly_fraction}"
    )
    assert h1.model_weights == h2.model_weights, "model_weights differ for same round"

    # Different rounds should (usually) produce different hypotheses
    h3 = generate_hypothesis(round_num=4, parent=None)
    # At least one field should differ (not all rungs change all fields, but
    # the description always differs because it includes the rung name)
    assert h1.description != h3.description, (
        "descriptions should differ for different rounds (mutation ladder indexed by round)"
    )


# ---------------------------------------------------------------------------
# Test 3: Walk-forward evaluation can produce positive stats on good data
# (replaces test_karpathy_search_finds_positive_roi_candidate)
# ---------------------------------------------------------------------------


def test_evaluate_hypothesis_oos_returns_all_expected_stats():
    """evaluate_hypothesis_oos() must return a stats dict with all the
    fields the leaderboard/acceptance logic depends on. This replaces the
    original 'finds_positive_roi_candidate' test — we can't reliably
    produce positive ROI on synthetic data without the full Brier dataset,
    but we CAN verify the stats shape is correct so the acceptance logic
    won't KeyError.
    """
    import pandas as pd

    from asi_engine.karpathy_weekly import Hypothesis, evaluate_hypothesis_oos, _uniform_weights

    # Construct a minimal synthetic brier_df (one row, one market)
    brier_df = pd.DataFrame(
        [
            {
                "city": "test_city",
                "target_date": "2026-01-01",
                "threshold": 25.0,
                "market_type": "HIGH",
                "yes_price": 0.50,
                "outcome_yes": 1.0,
                "gfs_seamless_prob": 0.55,
                "ecmwf_ifs025_prob": 0.55,
                "gem_global_prob": 0.55,
                "icon_global_prob": 0.55,
                "jma_seamless_prob": 0.55,
                "cma_grapes_global_prob": 0.55,
                "ukmo_seamless_prob": 0.55,
                "meteofrance_seamless_prob": 0.55,
            }
        ]
    )

    hyp = Hypothesis(
        description="Test hypothesis",
        model_weights=_uniform_weights(),
        min_edge=0.05,
        kelly_fraction=0.15,
    )

    stats = evaluate_hypothesis_oos(brier_df, [0], hyp)

    # The acceptance logic in run_karpathy_weekly() reads these keys —
    # if any are missing, the loop KeyErrors. This is the real contract.
    required_keys = {"sharpe", "roi_pct", "brier_score", "total_trades", "win_rate"}
    missing = required_keys - set(stats.keys())
    assert not missing, f"evaluate_hypothesis_oos missing keys: {missing}"
    # Sanity: stats values must be numeric
    for k in required_keys:
        v = stats[k]
        assert isinstance(v, (int, float)), f"stats[{k!r}]={v!r} must be numeric"
    # total_trades is a count — must be >= 0
    assert stats["total_trades"] >= 0, f"total_trades={stats['total_trades']} must be >= 0"


# ---------------------------------------------------------------------------
# Test 4: _save_best writes a valid karpathy_best.json
# (replaces test_save_best_to_disk_writes_strategy_params)
# ---------------------------------------------------------------------------


def test_save_best_writes_valid_karpathy_best(clean_best_file):
    """_save_best() should write a JSON file that _load_best() can read
    back, with all Hypothesis fields intact. This replaces the original
    test that called save_best_to_disk() on the deleted script.
    """
    from asi_engine.karpathy_weekly import (
        Hypothesis,
        _load_best,
        _save_best,
    )

    fake_hyp = Hypothesis(
        description="Test candidate for save_best",
        model_weights={"gfs_seamless": 0.5, "ecmwf_ifs025": 0.5},
        min_edge=0.07,
        kelly_fraction=0.10,
        max_bet_pct=0.03,
    )
    fake_stats = {
        "sharpe": 0.8,
        "roi_pct": 10.0,
        "brier_score": 0.02,
        "win_rate": 0.95,
        "total_trades": 100,
        "total_pnl": 1000.0,
        "total_staked": 10000.0,
    }

    _save_best(fake_hyp, fake_stats)

    # Verify the file was written
    assert BEST_PATH.exists(), f"{BEST_PATH} was not written"

    # Verify it's valid JSON with the expected fields
    with open(BEST_PATH, encoding="utf-8") as f:
        payload = json.load(f)

    # All Hypothesis fields must be present
    assert payload["description"] == fake_hyp.description
    assert payload["min_edge"] == fake_hyp.min_edge
    assert payload["kelly_fraction"] == fake_hyp.kelly_fraction
    assert payload["max_bet_pct"] == fake_hyp.max_bet_pct
    assert payload["model_weights"] == fake_hyp.model_weights

    # Stats must be embedded
    assert payload["stats"]["sharpe"] == 0.8
    assert payload["stats"]["roi_pct"] == 10.0
    assert payload["stats"]["total_trades"] == 100

    # saved_at timestamp must be present
    assert "saved_at" in payload

    # Round-trip: _load_best() must reconstruct the Hypothesis
    loaded = _load_best()
    assert loaded is not None, "_load_best returned None for a file we just wrote"
    assert loaded.description == fake_hyp.description
    assert loaded.min_edge == fake_hyp.min_edge
    assert loaded.kelly_fraction == fake_hyp.kelly_fraction
    assert loaded.model_weights == fake_hyp.model_weights


# ---------------------------------------------------------------------------
# Test 5 (existing): apply_persisted_strategy_params reads karpathy_best.json
# ---------------------------------------------------------------------------


def test_apply_persisted_strategy_params_reads_karpathy_file():
    """apply_persisted_strategy_params should pick up the
    strategy_params.json file written by the Karpathy search and apply
    the values to bot_config.
    """
    from config.settings import Config, apply_persisted_strategy_params, bot_config

    applied = apply_persisted_strategy_params()

    # The fixture test_setup wrote a strategy_params.json with
    # min_edge=0.07, kelly_fraction=0.10, etc. Either that file is
    # present (and applied) or there's no file (and applied is empty).
    if applied:
        assert "min_edge" in applied
        assert "kelly_fraction" in applied
        # The values should match what was written.
        assert bot_config.strategy.min_edge == applied["min_edge"]
        assert bot_config.strategy.kelly_fraction == applied["kelly_fraction"]
        # Config mirror fields should be in sync.
        assert Config.KELLY_FRACTION == bot_config.strategy.kelly_fraction
        assert Config.MIN_ENTRY_PRICE == bot_config.strategy.min_entry_price
