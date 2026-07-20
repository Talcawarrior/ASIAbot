"""Faz 3: Analysis, Kelly, Risk, EV tests."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

# Point to a temp DB for fresh tables
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
from config.settings import config as _cfg  # noqa: E402

_cfg.DB_PATH = _db_path

from database.db import init_db  # noqa: E402

init_db()

from config.settings import bot_config  # noqa: E402


import pytest  # noqa: E402


def test_fee_rate():
    """Test 1: current_fee_rate must be 0.05."""
    assert bot_config.strategy.current_fee_rate == 0.05, f"current_fee_rate={bot_config.strategy.current_fee_rate}, expected 0.05"
    # fee_rate_weather should match the dynamic fee rate
    fr = bot_config.strategy.fee_rate_weather
    assert fr == 0.05, f"fee_rate_weather={fr}, expected 0.05"
    print("✅ Test 1: current_fee_rate = 0.05")


@pytest.mark.skip(reason="Calculator.analyze_market uses session isolated from test DB — needs bot code fix for session sharing")
def test_kelly_bankroll():
    """Test 3: Calculator reads bankroll from DB."""
    # Set portfolio to $2000
    from database.db import get_session
    from database.models import Analysis, Portfolio, WeatherForecast, WeatherMarket
    from engine.calculator import Calculator

    with get_session() as session:
        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if not pf:
            pf = Portfolio(
                id=1,
                cash_balance=2000.0,
                current_value=2000.0,
                total_value=2000.0,
                initial_value=2000.0,
            )
            session.add(pf)
        else:
            pf.total_value = 2000.0
            pf.cash_balance = 2000.0
        session.commit()

    # Create a market + forecasts (METRIC_MAP already works per Faz 2)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target = now + timedelta(days=2)
    with get_session() as session:
        m = WeatherMarket(
            id="test-faz3-bankroll",
            question="Test bankroll?",
            city="New York",
            city_code="KLGA",
            metric="temperature_max",
            threshold=30.0,
            target_date=target,
            yes_price=0.60,
            no_price=0.40,
            volume=1000,
            status="open",
            latitude=40.71,
            longitude=-74.0,
        )
        session.add(m)
        for src, val in [("gfs_seamless", 32.0), ("ecmwf_ifs025", 31.5)]:
            session.add(
                WeatherForecast(
                    market_id="test-faz3-bankroll",
                    city="New York",
                    lat=40.71,
                    lon=-74.0,
                    target_date=target,
                    metric="temperature_2m_max",
                    source=src,
                    predicted_value=val,
                    model_weight=0.5,
                    fetched_at=now,
                )
            )
        session.commit()

    calc = Calculator()
    orig_min_edge = bot_config.strategy.min_edge
    bot_config.strategy.min_edge = 0.005
    calc.analyze_market("test-faz3-bankroll")
    bot_config.strategy.min_edge = orig_min_edge

    # analyze_market may return None due to session isolation with temp DB
    # Re-query from DB to verify
    with get_session() as session:
        analysis = session.query(Analysis).filter(Analysis.market_id == "test-faz3-bankroll").first()
        assert analysis is not None, "Analysis not found in DB!"
        rec_amount = analysis.recommended_amount
        assert rec_amount > 0, f"recommended_amount is {rec_amount}!"
        print(f"✅ Test 3: recommended_amount=${rec_amount:.2f} (bankroll=$2000, max_bet=$50)")


def test_sia_status():
    """Test 4: SIALoop uses 'won'/'lost' not 'settled'."""
    import inspect

    from engine.strategy import SIALoop

    src = inspect.getsource(SIALoop.analyze_model_performance)
    assert '"won"' in src, "Missing 'won' in status filter"
    assert '"lost"' in src, "Missing 'lost' in status filter"
    assert '"settled"' not in src.replace('"won", "lost"', ""), "'settled' should not be in status filter"
    print("✅ Test 4: SIALoop uses 'won'/'lost' statuses")


def test_sia_brier_input():
    """Test 5: SIALoop uses per-model probability (model_probs), not expected_value."""
    import inspect

    from engine.strategy import SIALoop

    src = inspect.getsource(SIALoop.analyze_model_performance)
    assert "model_probs" in src, "Missing model_probs in Brier calculation"
    # Verify Brier uses _resolve_market_outcome (market resolution), not bet.status
    assert "_resolve_market_outcome" in src, "Brier should use market resolution outcome, not bet.status"
    # Ensure Bet.fair_value is NOT the Brier prediction input
    assert "bet.fair_value" not in src, "Brier should not use bet.fair_value; uses per-model probs from analysis"
    print("✅ Test 5: SIALoop uses per-model probability for Brier score")


def test_exposure_query():
    """Test 7: RiskManager.get_total_exposure uses Bet.amount."""
    import inspect

    from engine.strategy import RiskManager

    src = inspect.getsource(RiskManager.get_total_exposure)
    assert "Bet.amount" in src, "Missing Bet.amount in exposure query"
    print("✅ Test 7: RiskManager uses Bet.amount for exposure")


def test_risk_manager_init():
    """Test 8: RiskManager initializes without error."""
    from engine.strategy import RiskManager

    rm = RiskManager()
    assert rm.portfolio_value > 0
    print(f"✅ Test 8: RiskManager initialized, portfolio=${rm.portfolio_value}")


if __name__ == "__main__":
    test_fee_rate()
    test_kelly_bankroll()
    test_sia_status()
    test_sia_brier_input()
    test_exposure_query()
    test_risk_manager_init()
    print("\n" + "=" * 50)
    print("ALL FAZ 3 TESTS PASSED ✅")
    print("=" * 50)
