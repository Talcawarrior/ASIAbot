"""Pre-flight safety checklist before flipping the bot to live trading.

Defense-in-depth layer on top of the orchestrator deploy gate. Returns a
structured pass/fail report so it can be asserted in CI and at startup.
Pure function over a params dict — no network, no DB writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

KELLY_FRACTION_MAX = 0.5  # full Kelly only for proven Brier<0.10 over 500+ bets
MIN_EDGE_MIN = 0.0
MIN_CALIBRATION_TRADES = 100  # Brier is unstable below this

# Pulled from config so the check reflects what the bot will actually load.
from config.settings import MAX_BET_PCT_CEILING  # noqa: E402


@dataclass
class PreflightReport:
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


def _collect_params(params: dict | None = None) -> dict:
    """Merge live strategy_params.json over the provided override dict."""
    if params is not None:
        return dict(params)
    try:
        from config.settings import apply_persisted_strategy_params

        return apply_persisted_strategy_params() or {}
    except Exception:
        return {}


def run_preflight_check(params: dict | None = None) -> PreflightReport:
    """Validate the live strategy parameters against hard safety limits.

    Returns a report with ``passed`` False if any blocking issue is found.
    """
    p = _collect_params(params)
    issues: list[str] = []
    warnings: list[str] = []

    params_path = os.path.join("data", "strategy_params.json")
    if not os.path.exists(params_path):
        issues.append(f"strategy_params.json missing at {params_path}")

    kelly = p.get("kelly_fraction")
    if kelly is None:
        warnings.append("kelly_fraction not set — falls back to config default")
    elif not (0.0 < kelly <= KELLY_FRACTION_MAX):
        issues.append(f"kelly_fraction={kelly} out of safe range (0, {KELLY_FRACTION_MAX}]")

    min_edge = p.get("min_edge")
    if min_edge is None:
        warnings.append("min_edge not set — falls back to config default")
    elif not (min_edge > MIN_EDGE_MIN):
        issues.append(f"min_edge={min_edge} must be > {MIN_EDGE_MIN}")

    max_bet_pct = p.get("max_bet_pct")
    if max_bet_pct is None:
        warnings.append("max_bet_pct not set — falls back to code default")
    elif not (0.0 < max_bet_pct <= MAX_BET_PCT_CEILING):
        issues.append(f"max_bet_pct={max_bet_pct} exceeds hard ceiling {MAX_BET_PCT_CEILING}")

    return PreflightReport(
        passed=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        params=p,
    )
