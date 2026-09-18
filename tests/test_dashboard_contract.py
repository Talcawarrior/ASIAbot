"""Dashboard contract tests: API shape the UI depends on.

Regression tests for bugs found live by the user (not by CI):
- fee $0: backend never sent total_entry_fee
- ST label: unknown exit types fell back to ST badge
- signal-decay cutting winners
- missing threshold / price bands
"""

import pytest

httpx = pytest.importorskip("httpx", reason="httpx not installed (needed for FastAPI TestClient)")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    import main as app_module

    with TestClient(app_module.app) as c:
        yield c


def test_status_fee_fields(client):
    """/api/status portfolio must carry fee fields (fee $0 bug)."""
    body = client.get("/api/status").json()
    p = body["portfolio"]
    assert "total_entry_fee" in p, "missing portfolio.total_entry_fee"
    assert "entry_fee_trade_count" in p, "missing portfolio.entry_fee_trade_count"
    assert p["total_entry_fee"] >= 0
    assert p["entry_fee_trade_count"] >= 0


def test_history_threshold_and_bands(client):
    """/api/history rows must carry threshold; stats must carry bands."""
    body = client.get("/api/history").json()
    assert "history" in body and "stats" in body
    assert "roi_by_price_band" in body["stats"], "missing roi_by_price_band"
    assert isinstance(body["stats"]["roi_by_price_band"], list)
    for h in body["history"][:50]:
        assert "threshold" in h, f"row {h.get(chr(105) + chr(100))} missing threshold"


def test_history_exit_types_known(client):
    """Every exit_type must be renderable (unknown -> ST fallback bug)."""
    known = {"ST", "TP", "SL", "TS", "TD", "SD", "PT", "OT", "RT", "TL", "CL"}
    body = client.get("/api/history").json()
    seen = {h.get("exit_type", "ST") for h in body["history"]}
    unknown = seen - known
    assert not unknown, f"unrenderable exit types (would show as ST): {unknown}"


def test_signal_decay_holds_winners():
    """Signal-decay must never cut profitable positions (Chengdu +$188 case)."""
    from types import SimpleNamespace as NS

    from engine.strategy import RiskManager

    rm = RiskManager(db_session=None, cfg=None)
    profitable = NS(
        fair_value=0.01,
        entry_price=0.01,
        price=0.01,
        unrealized_pnl=50.0,
        stake=5,
        amount=5,
    )
    ok, _ = rm.check_signal_decay(profitable, NS(estimated_probability=0.35), 0.50)
    assert ok is False, "signal-decay cut a +1000% winner!"
    loser = NS(
        fair_value=0.25,
        entry_price=0.25,
        price=0.25,
        unrealized_pnl=-1.0,
        stake=5,
        amount=5,
    )
    ok, reason = rm.check_signal_decay(loser, NS(estimated_probability=0.02), 0.10)
    assert ok is True, "signal-decay did not exit a decayed loser"
    assert "signal_decay" in reason


def test_edge_calibration_shape(client):
    """/api/edge-calibration must return buckets (Health tab depends on it)."""
    body = client.get("/api/edge-calibration").json()
    assert "buckets" in body and isinstance(body["buckets"], list)
    assert len(body["buckets"]) > 0
    for b in body["buckets"]:
        for key in ("band", "trades", "wins", "win_rate", "pnl", "roi"):
            assert key in b, f"missing {key} in edge bucket"
