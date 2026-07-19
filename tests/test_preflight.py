"""Pre-flight safety checklist tests.

These guard the live trading parameters before the bot is allowed to trade.
Any blocking issue => passed=False => startup should refuse to go live.
"""

from asi_engine.preflight import (
    KELLY_FRACTION_MAX,
    MIN_EDGE_MIN,
    PreflightReport,
    run_preflight_check,
)


def test_preflight_passes_with_safe_params():
    report = run_preflight_check({"min_edge": 0.01, "kelly_fraction": 0.25})
    assert isinstance(report, PreflightReport)
    assert report.passed is True
    assert report.issues == []


def test_preflight_fails_on_full_kelly():
    report = run_preflight_check(
        {"min_edge": 0.01, "kelly_fraction": 1.0}  # full Kelly = ruin risk
    )
    assert report.passed is False
    assert any("kelly_fraction" in i for i in report.issues)


def test_preflight_fails_on_negative_edge():
    report = run_preflight_check({"min_edge": -0.01, "kelly_fraction": 0.25})
    assert report.passed is False
    assert any("min_edge" in i for i in report.issues)


def test_preflight_fails_on_excessive_max_bet_pct():
    report = run_preflight_check({"min_edge": 0.01, "kelly_fraction": 0.25, "max_bet_pct": 0.5})
    assert report.passed is False
    assert any("max_bet_pct" in i for i in report.issues)


def test_preflight_warns_when_params_missing():
    # No max_bet_pct / kelly not specified => not blocking but warned.
    report = run_preflight_check({})
    assert report.passed is True
    assert report.warnings  # informs operator of implicit defaults


def test_preflight_kelly_bounds_are_sane():
    assert 0.0 < KELLY_FRACTION_MAX <= 0.5
    assert MIN_EDGE_MIN == 0.0
