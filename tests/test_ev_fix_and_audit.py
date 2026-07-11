"""EV FIX + Duplicate Bet Prevention testleri.

Bu testler su senaryolari kapsar:
1. EV FIX: Yüksek EV'ye yüksek bet, düşük EV'ye düşük bet
2. Dinamik max_bet_pct edge band'ine göre
3. Dinamik kelly_fraction edge band'ine göre
4. min_bet floor: Kelly çok düşükse bet açma
5. Duplicate bet önleme (cooldown, no_existing_bet)
6. BetStatus enum değerleri
7. Model trend enum (up/down/stable)
8. Sharpe ratio risk-free rate
9. Ladder pyramiding vs averaging
"""

import os


# ── EV FIX Testleri ─────────────────────────────────────────────────────


def test_dynamic_max_bet_pct_edge_bands():
    """EV FIX: Edge band'ine göre dinamik max_bet_pct.

    Not: base_pct default 0.006 (config.MAX_BET_PCT). Testlerde eski
    band mantığını (base_pct=0.03) test etmek için explicit geçiyoruz.
    """
    from utils.kelly import dynamic_max_bet_pct

    # Test with explicit base_pct=0.03 (old band logic)
    assert dynamic_max_bet_pct(0.30, base_pct=0.03) == 0.05, "Edge %30 → %5 cap olmali"
    assert dynamic_max_bet_pct(0.20, base_pct=0.03) == 0.05, "Edge %20 → %5 cap olmali"
    # Orta EV → base_pct
    assert dynamic_max_bet_pct(0.15, base_pct=0.03) == 0.03, "Edge %15 → base_pct cap olmali"
    assert dynamic_max_bet_pct(0.10, base_pct=0.03) == 0.03, "Edge %10 → base_pct cap olmali"
    # Düşük EV → base_pct * 0.5
    assert dynamic_max_bet_pct(0.05, base_pct=0.03) == 0.015, "Edge %5 → base_pct*0.5 cap olmali"
    assert dynamic_max_bet_pct(0.06, base_pct=0.03) == 0.015, "Edge %6 → base_pct*0.5 cap olmali"

    # Test with production default base_pct=0.006
    assert dynamic_max_bet_pct(0.30) == 0.05, "Edge %30 → %5 cap olmali (prod default)"
    assert dynamic_max_bet_pct(0.10) == 0.006, "Edge %10 → base_pct cap olmali (prod default)"
    assert dynamic_max_bet_pct(0.05) == 0.003, "Edge %5 → base_pct*0.5 cap olmali (prod default)"


def test_dynamic_kelly_fraction_edge_bands():
    """EV FIX: Edge band'ine göre dinamik kelly_fraction."""
    from utils.kelly import dynamic_kelly_fraction

    # Yüksek EV → quarter Kelly (0.25)
    assert dynamic_kelly_fraction(0.30) == 0.25, "Edge %30 → 0.25 fraction olmali"
    assert dynamic_kelly_fraction(0.20) == 0.25, "Edge %20 → 0.25 fraction olmali"
    # Orta EV → sub-quarter (0.15)
    assert dynamic_kelly_fraction(0.15) == 0.15, "Edge %15 → 0.15 fraction olmali"
    assert dynamic_kelly_fraction(0.10) == 0.15, "Edge %10 → 0.15 fraction olmali"
    # Düşük EV → 0.10
    assert dynamic_kelly_fraction(0.05) == 0.10, "Edge %5 → 0.10 fraction olmali"


def test_ev_proportional_sizing():
    """EV FIX: Yüksek EV → yüksek bet, düşük EV → düşük bet.

    Eski sabit %3 cap yüksek EV'yi sınırlıyordu (edge %30 ve %10 aynı $29.70).
    Artık dinamik sizing ile EV'ye orantılı.

    Not: max_bet_pct default 0.006 (config), dynamic bands:
    - edge >= 0.20 → 0.05
    - edge >= 0.10 → 0.006
    - edge < 0.10 → 0.003
    """
    from utils.kelly import kelly_bet_amount

    portfolio = 1000.0
    # Edge %30 (yüksek EV) → max_bet_pct=0.05
    bet_high = kelly_bet_amount(portfolio, 0.80, 0.50, edge=0.30)
    # Edge %10 (orta EV) → max_bet_pct=0.006
    bet_mid = kelly_bet_amount(portfolio, 0.60, 0.50, edge=0.10)
    # Edge %5 (düşük EV) → max_bet_pct=0.003
    bet_low = kelly_bet_amount(portfolio, 0.55, 0.50, edge=0.05)

    print(f"  Yüksek EV (edge %30): ${bet_high}")
    print(f"  Orta EV (edge %10):   ${bet_mid}")
    print(f"  Düşük EV (edge %5):   ${bet_low}")

    # EV'ye orantılı: yüksek > orta > düşük
    assert bet_high > bet_mid, f"Yüksek EV ({bet_high}) > orta EV ({bet_mid}) olmali"
    assert bet_mid > bet_low, f"Orta EV ({bet_mid}) > düşük EV ({bet_low}) olmali"
    # Yüksek EV eski $29.70'den büyük olmalı (cap kalktı)
    assert bet_high > 30.0, f"Yüksek EV bet (${bet_high}) eski cap'ten ($30) büyük olmali"


def test_min_bet_floor_no_force():
    """EV FIX: Kelly çok düşükse min_bet'e zorlama, bet açma.

    Eski kod: Kelly $0.10 önerse bile $1.0'e yapışıyordu (over-betting).
    Yeni: Kelly < min_bet/2 ise return 0 (bet açma).
    """
    from utils.kelly import kelly_bet_amount

    # Kelly çok düşük (edge %5.1, p=0.551, price=0.50)
    # f_star ≈ 0.102, fraction=0.10 → fractional=0.0102 → amount=$1.02
    # max_bet_pct=0.003 → max_amount=$3 → capped at $1.02
    # amount >= min_bet/2 (0.5) → returns max(1.02, 1.0) = 1.02
    bet = kelly_bet_amount(100.0, 0.551, 0.50, edge=0.051, min_bet=1.0)
    # With dynamic max_bet_pct=0.003, max_amount=$0.3, so bet=$0.3
    # This is < min_bet/2 (0.5) → should return 0
    assert bet == 0.0, f"Kelly çok düşükse bet=0 olmali, got {bet}"

    # Kelly biraz daha yüksek (edge %10, p=0.60, price=0.50)
    # f_star ≈ 0.20, fraction=0.15 → fractional=0.03 → amount=$30
    # max_bet_pct=0.006 → max_amount=$60 → capped at $30
    # amount >= min_bet/2 → returns max(30, 1.0) = 30
    bet2 = kelly_bet_amount(1000.0, 0.60, 0.50, edge=0.10, min_bet=1.0)
    assert bet2 >= 1.0, f"Yeterli Kelly varsa min_bet'e floor olmali, got {bet2}"


# ── Duplicate Bet Prevention Testleri ────────────────────────────────────


def test_no_existing_bet_gate_in_place_bet():
    """HATA-1: no_existing_bet gate'i place_bet() içinde olmalı (defense in depth)."""
    import inspect
    from executor.bet_placer import BetPlacer

    # Check both place_bet and the helper method
    source = inspect.getsource(BetPlacer.place_bet)
    helper_source = inspect.getsource(BetPlacer._check_no_existing_bet)
    combined = source + helper_source
    assert "no_existing_bet" in combined
    assert "OPEN_BET_STATUSES" in combined
    # HATA-3 + HATA-14: closed_at + settled_at cooldown
    assert "closed_at" in combined, "closed_at cooldown olmali (HATA-3)"
    assert "settled_at" in combined, "settled_at cooldown olmali (HATA-3)"
    assert "REOPEN_COOLDOWN_HOURS" in combined, "cooldown env var olmali (HATA-1)"
    assert "_cooldown_cutoff" in combined


def test_bet_status_enum_complete():
    """HATA-10: BetStatus enum'ında closed_early ve rejected olmalı."""
    from database.models import BetStatus

    values = [s.value for s in BetStatus]
    assert "closed_early" in values
    assert "rejected" in values
    assert "won" in values
    assert "lost" in values


def test_reopen_cooldown_hours_env_var(monkeypatch):
    """REOPEN_COOLDOWN_HOURS env var'ı değiştirilebilir."""
    hours = int(os.getenv("REOPEN_COOLDOWN_HOURS", "24"))
    assert hours == 24
    monkeypatch.setenv("REOPEN_COOLDOWN_HOURS", "168")  # 1 hafta
    hours = int(os.getenv("REOPEN_COOLDOWN_HOURS", "24"))
    assert hours == 168


# ── Trend Enum Testi ─────────────────────────────────────────────────────


def test_model_trend_up_down_stable():
    """HATA-4: Backend trend 'up'/'down'/'stable' göndermeli."""
    import inspect
    from api import get_asi_weights

    source = inspect.getsource(get_asi_weights)
    assert 'trend = "up"' in source
    assert 'trend = "down"' in source
    assert 'trend = "improving"' not in source
    assert 'trend = "declining"' not in source


# ── Sharpe Ratio Testi ───────────────────────────────────────────────────


def test_sharpe_includes_risk_free_rate():
    """HATA-5: Sharpe ratio risk-free rate içermeli."""
    import inspect
    from api import get_status

    source = inspect.getsource(get_status)
    assert "risk_free" in source or "rf" in source.lower()


# ── Ladder Pyramiding Testi ──────────────────────────────────────────────


def test_ladder_pyramiding_in_bet_placer():
    """EV FIX: Ladder pyramiding (yüksek edge → fiyat yükselince ekle)."""
    import inspect
    from executor.bet_placer import BetPlacer

    source = inspect.getsource(BetPlacer.place_bet)
    helper_source = inspect.getsource(BetPlacer._build_ladder_orders)
    combined = source + "\n" + helper_source
    assert "pyramiding" in combined, "Pyramiding modu olmali"
    assert "averaging" in combined, "Averaging modu olmali"
    # Yüksek edge için L1 %70
    assert "0.70" in combined, "Yüksek edge için L1 %70 olmali"


def test_ladder_fill_pyramiding_in_scheduler():
    """EV FIX: scheduler L2/L3 fill'de pyramiding desteği olmalı."""
    import inspect
    from jobs.scheduler import run_update_prices

    source = inspect.getsource(run_update_prices)
    assert "pyramiding" in source, "Pyramiding desteği olmali"
    assert "rung_mode" in source or "mode" in source


# ── Backtest Simulator Testi ─────────────────────────────────────────────


def test_backtest_uses_slippage_gas():
    """HATA-12: backtest_simulator slippage + gas kullanmalı."""
    import inspect
    from asi_engine.backtest_simulator import BacktestSimulator

    src = inspect.getsource(BacktestSimulator.run_backtest) + inspect.getsource(BacktestSimulator.run_extended_backtest)
    assert "estimate_slippage" in src
    assert "GAS_COST_USD" in src
    # Eski fixed 5% fee drag kalkmış olmalı (kod satırı olarak)
    code_lines = [
        line for line in src.split("\n") if not line.strip().startswith("#") and "ev = sim_edge - 0.05" in line
    ]
    assert not code_lines, "Eski fixed 5% fee drag kalkmali"


def test_backtest_min_bet_zero():
    """EV FIX: backtest'te min_bet=0 olmalı (düşük Kelly'yi zorla açma)."""
    import inspect
    from asi_engine.backtest_simulator import BacktestSimulator

    src = inspect.getsource(BacktestSimulator.run_backtest)
    assert "min_bet=0.0" in src or "min_bet=0" in src


# ── Karpathy Kelly Testi ─────────────────────────────────────────────────


def test_karpathy_uses_utils_kelly():
    """HATA-11: Karpathy utils/kelly.py kullanmalı."""
    import inspect
    from asi_engine import karpathy_weekly

    source = inspect.getsource(karpathy_weekly)
    assert "from utils.kelly import" in source
    assert "b = (1.0 / entry) - 1.0" not in source


# ── Frontend Testleri (Removed - dashboard moved to separate repo) ───────────
# def test_frontend_exit_price_simplified():
#     """HATA-6: Frontend exit_price fallback basitleştirilmiş."""
#     with open("src/lib/api.ts", encoding="utf-8") as f:
#         content = f.read()
#     assert "1.0 + h.realized_pnl" not in content
#     assert "function portfolioValue(" in content, "portfolioValue helper olmali (HATA-13)"


# ── WebSocket Testi ──────────────────────────────────────────────────────


def test_websocket_broadcast_in_bot_loop():
    """HATA-15: bot_loop WebSocket broadcast yapmalı."""
    import inspect
    from bot_loop import scan_and_bet_loop

    source = inspect.getsource(scan_and_bet_loop)
    assert "_safe_broadcast" in source or "broadcast_message" in source


# ── Performance Testleri ─────────────────────────────────────────────────


def test_forecast_days_is_16():
    """Open-Meteo supports up to 16 days forecast."""
    import inspect
    from engine.calculator import WeatherEngine

    source = inspect.getsource(WeatherEngine.get_multi_model_forecast)
    assert '"forecast_days": 16' in source


def test_weather_concurrency_increased():
    """PER-3: Weather Semaphore 20, throttle 1.0 olmalı."""
    with open("scrapers/meteo.py") as f:
        content = f.read()
    assert "_MAX_CONCURRENT = 20" in content
    assert "_THROTTLE_INTERVAL = 1.0" in content


def test_warm_start_method_exists():
    """PER-5: WeatherEngine.warm_start_from_db metodu olmalı."""
    from engine.calculator import WeatherEngine

    assert hasattr(WeatherEngine, "warm_start_from_db")


def test_bot_loop_parallel():
    """PER-2: bot_loop paralel çalışmalı."""
    import inspect
    from bot_loop import scan_and_bet_loop

    source = inspect.getsource(scan_and_bet_loop)
    assert "asyncio.gather" in source


# ── Dead Code Testi ──────────────────────────────────────────────────────


def test_exit_price_from_pnl_removed():
    """HATA-16: exit_price_from_pnl dead code kaldırılmalı."""
    import utils.formulas as fm

    assert not hasattr(fm, "exit_price_from_pnl")


# ── Orderbook Depth Testi ────────────────────────────────────────────────


def test_check_orderbook_depth_uses_live_api():
    """HATA-2: check_orderbook_depth gerçek API kullanmalı (mock değil)."""
    import inspect
    from utils.slippage import check_orderbook_depth

    source = inspect.getsource(check_orderbook_depth)
    # Yeni kod resolvedmarkets_ingest (gerçek API) import etmeli
    assert "resolvedmarkets_ingest" in source
    # Eski resolved_markets_helper (mock) import'u kalkmış olmalı
    # (comment'te geçebilir, kod satırını kontrol et)
    code_lines = [
        line
        for line in source.split("\n")
        if not line.strip().startswith("#") and "resolved_markets_helper" in line and "import" in line
    ]
    assert not code_lines, f"resolved_markets_helper import kalkmali (HATA-2). Bulundu: {code_lines}"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
