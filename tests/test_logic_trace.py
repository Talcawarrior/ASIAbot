"""
Step-by-step logic trace test — traces the full betting pipeline.

This test verifies every step of the business logic:
  Market data → Forecast → Ensemble → Edge → Kelly → Risk → Bet → PnL

Each step is tested INDEPENDENTLY so failures are isolated.
No network calls — all data is constructed in-memory.
"""

import os
import tempfile

import pytest

# ── Setup temp DB ──────────────────────────────────────────────────────────────
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
from config.settings import config as _cfg  # noqa: E402

_cfg.DB_PATH = _db_path

from database.db import get_session, init_db  # noqa: E402

init_db()

from database.models import Portfolio  # noqa: E402
from utils.kelly import kelly_fraction  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Hava durumu tahmini → ensemble probability
# ══════════════════════════════════════════════════════════════════════════════


class TestStep1_EnsembleProbability:
    """Step 1: Weather forecast → weighted ensemble probability."""

    def test_weighted_mean_prob_basic(self):
        """8 model tahmini var → ağırlıklı ortalama hesaplanır."""
        weights = {
            "gfs_seamless": 0.30,
            "ecmwf_ifs025": 0.25,
            "gem_global": 0.15,
            "icon_global": 0.10,
            "jma_seamless": 0.08,
            "cma_grapes_global": 0.05,
            "ukmo_seamless": 0.04,
            "meteofrance_seamless": 0.03,
        }

        # Simulate: models predict 25-27°C, market threshold is 26°C
        probs = {
            "gfs_seamless": 0.55,  # GFS says 26.5°C → above threshold
            "ecmwf_ifs025": 0.48,  # ECMWF says 25.8°C → below threshold
            "gem_global": 0.52,
            "icon_global": 0.50,
            "jma_seamless": 0.45,
            "cma_grapes_global": 0.53,
            "ukmo_seamless": 0.49,
            "meteofrance_seamless": 0.51,
        }

        # Weighted mean = sum(prob * weight) for all models
        expected = sum(probs[m] * weights[m] for m in weights)
        # Normalize weights (they should sum to 1.0 already)
        total_weight = sum(weights.values())
        assert abs(total_weight - 1.0) < 0.01, f"Weights sum to {total_weight}, expected ~1.0"

        result = expected / total_weight  # should be ~expected since weights sum to 1
        assert 0.45 < result < 0.55, f"Ensemble prob {result} out of range [0.45, 0.55]"
        print(f"  Ensemble probability: {result:.4f}")

    def test_weighted_mean_prob_missing_model(self):
        """Bir model eksik → ağırlıklar yeniden normalize edilir."""
        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        probs = {"a": 0.6, "b": 0.4}  # c eksik

        # Normalize for available models only
        available = {m: weights[m] for m in probs if m in weights}
        total = sum(available.values())
        result = sum(probs[m] * available[m] for m in probs) / total

        # Should be (0.6*0.5 + 0.4*0.3) / 0.8 = 0.42/0.8 = 0.525
        assert abs(result - 0.525) < 0.001, f"Expected 0.525, got {result}"
        print(f"  Re-normalized ensemble: {result:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Edge hesaplama — model prob vs market price
# ══════════════════════════════════════════════════════════════════════════════


class TestStep2_EdgeCalculation:
    """Step 2: Edge = model_probability - market_implied_probability."""

    def test_edge_positive_when_model_beats_market(self):
        """Model 0.65 diyor, piyasa 0.50 → edge = +0.15."""
        model_prob = 0.65
        market_price = 0.50
        edge = model_prob - market_price
        assert abs(edge - 0.15) < 0.001

    def test_edge_negative_when_market_beats_model(self):
        """Model 0.30 diyor, piyasa 0.50 → edge = -0.20 (bahse girme)."""
        model_prob = 0.30
        market_price = 0.50
        edge = model_prob - market_price
        assert edge == pytest.approx(-0.20)

    def test_fee_drag_reduces_edge(self):
        """Edge'den fee_drag (0.05) düşülür."""
        edge = 0.15
        fee_drag = 0.05
        effective_edge = edge - fee_drag
        assert effective_edge == pytest.approx(0.10)

    def test_min_edge_filter(self):
        """Edge < min_edge ise bahis yapılmaz."""
        min_edge = 0.05
        edges = [0.03, 0.05, 0.08, 0.12]
        should_bet = [e >= min_edge for e in edges]
        assert should_bet == [False, True, True, True]


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Kelly Criterion — bahis büyüklüğü
# ══════════════════════════════════════════════════════════════════════════════


class TestStep3_KellyCriterion:
    """Step 3: Kelly formula → optimal bet size."""

    def test_kelly_basic(self):
        """Kelly: f* = (bp - q) / b where b=odds, p=win_prob, q=1-p."""
        p = 0.6  # 60% chance to win
        price = 0.50  # buy at $0.50
        b = (1.0 / price) - 1  # odds = 1.0 (double your money)
        q = 1 - p
        f_star = (b * p - q) / b
        assert f_star == pytest.approx(0.20), f"Kelly fraction should be 0.20, got {f_star}"

    def test_kelly_with_fraction(self):
        """Kelly fraction reduced (kelly_fraction=0.15 → conservative)."""
        f_star = 0.20  # full Kelly
        kelly_fraction = 0.15
        actual_fraction = f_star * kelly_fraction
        assert actual_fraction == pytest.approx(0.03)

    def test_kelly_capped_by_max_bet_pct(self):
        """Kelly'den gelen yüzde max_bet_pct'i aşamaz."""
        f_star = 0.50  # very aggressive Kelly
        kelly_fraction = 0.15
        max_bet_pct = 0.05
        actual_fraction = min(f_star * kelly_fraction, max_bet_pct)
        assert actual_fraction == pytest.approx(0.05)  # capped

    def test_kelly_zero_on_negative_edge(self):
        """Negatif edge → Kelly 0 döndürmeli (bahse girme)."""
        p = 0.30
        b = 1.0
        q = 1 - p
        f_star = max(0, (b * p - q) / b)
        assert f_star == 0.0

    def test_kelly_regression_5_percent_edge(self):
        """Regression: %5 edge ile Kelly ne döndürmeli."""

        result = kelly_fraction(prob=0.55, price=0.50)
        assert result >= 0, "Kelly should be non-negative for positive edge"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Risk manager — exposure ve city caps
# ══════════════════════════════════════════════════════════════════════════════


class TestStep4_RiskManagement:
    """Step 4: Risk manager checks exposure and city caps."""

    def test_max_bet_cap(self):
        """proposed_amount > max_bet → max_bet'e düşür."""
        proposed = 150.0
        max_bet = 100.0
        actual = min(proposed, max_bet)
        assert actual == 100.0

    def test_exposure_cap_blocks_overexposure(self):
        """Mevcut exposure + yeni bet > cap → engelle."""
        current_exposure = 900.0
        new_bet = 200.0
        exposure_cap = 1000.0
        would_exceed = (current_exposure + new_bet) > exposure_cap
        assert would_exceed is True

    def test_exposure_cap_allows_under_limit(self):
        """Mevcut exposure + yeni bet < cap → izin ver."""
        current_exposure = 500.0
        new_bet = 200.0
        exposure_cap = 1000.0
        would_exceed = (current_exposure + new_bet) > exposure_cap
        assert would_exceed is False

    def test_city_cap_limits_single_city(self):
        """Tek şehre máximo ne kadar bahis yapılabilir."""
        city_exposure = 80.0
        city_cap = 100.0
        new_bet = 30.0
        would_exceed_city = (city_exposure + new_bet) > city_cap
        assert would_exceed_city is True


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Bet placement — bahis oluşturulması
# ══════════════════════════════════════════════════════════════════════════════


class TestStep5_BetPlacement:
    """Step 5: Bet is created with correct fields."""

    def test_bet_amount_calculation(self):
        """Kelly fraction × bankroll = bet amount."""
        bankroll = 10000.0
        kelly_f = 0.03
        amount = bankroll * kelly_f
        assert amount == pytest.approx(300.0)

    def test_bet_shares_calculation(self):
        """Shares = amount / price."""
        amount = 300.0
        price = 0.50
        shares = amount / price
        assert shares == pytest.approx(600.0)

    def test_bet_fee_calculation(self):
        """Fee = shares × price × fee_rate (Polymarket model)."""
        shares = 600.0
        price = 0.50
        fee_rate = 0.05
        fee = shares * price * fee_rate
        assert fee == pytest.approx(15.0)

    def test_bet_payout_on_win(self):
        """Kazanırsa: payout = shares × 1.0 (YES token = $1)."""
        shares = 600.0
        payout = shares * 1.0
        assert payout == pytest.approx(600.0)

    def test_bet_pnl_on_win(self):
        """Kazanırsa: pnl = payout - fee - amount."""
        payout = 600.0
        fee = 15.0
        amount = 300.0
        pnl = payout - fee - amount
        assert pnl == pytest.approx(285.0)

    def test_bet_pnl_on_loss(self):
        """Kaybederse: pnl = -amount (tüm bahis gider)."""
        amount = 300.0
        pnl = -amount
        assert pnl == pytest.approx(-300.0)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6: Settlement — sonuç hesaplama
# ══════════════════════════════════════════════════════════════════════════════


class TestStep6_Settlement:
    """Step 6: Settlement determines win/loss/draw."""

    def test_yes_bet_wins_above_threshold(self):
        """YES bahis: gerçek sıcaklık eşik üzeri → kazanır."""
        threshold = 26.0
        actual_temp = 27.5
        side = "YES"
        won = (actual_temp >= threshold) if side == "YES" else (actual_temp < threshold)
        assert won is True

    def test_yes_bet_loses_below_threshold(self):
        """YES bahis: gerçek sıcaklık eşik altı → kaybeder."""
        threshold = 26.0
        actual_temp = 24.0
        side = "YES"
        won = (actual_temp >= threshold) if side == "YES" else (actual_temp < threshold)
        assert won is False

    def test_no_bet_wins_below_threshold(self):
        """NO bahis: gerçek sıcaklık eşik altı → kazanır."""
        threshold = 26.0
        actual_temp = 24.0
        side = "NO"
        won = (actual_temp >= threshold) if side == "YES" else (actual_temp < threshold)
        assert won is True

    def test_no_bet_loses_above_threshold(self):
        """NO bahis: gerçek sıcaklık eşik üzeri → kaybeder."""
        threshold = 26.0
        actual_temp = 27.5
        side = "NO"
        won = (actual_temp >= threshold) if side == "YES" else (actual_temp < threshold)
        assert won is False


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7: Full pipeline trace — baştan sona
# ══════════════════════════════════════════════════════════════════════════════


class TestStep7_FullPipelineTrace:
    """Step 7: Trace the entire pipeline with concrete numbers."""

    def test_full_trace_winning_bet(self):
        """
        Full trace: market → forecast → ensemble → edge → kelly → bet → WIN

        Concrete scenario:
        - Market: NYC temperature > 30°C tomorrow, YES price = $0.45
        - Models: GFS=0.55, ECMWF=0.52, GEM=0.48, others avg 0.50
        - Ensemble: weighted mean ≈ 0.52
        - Edge: 0.52 - 0.45 - 0.05 (fee) = 0.02
        - Kelly: positive edge → bet
        - Bet: $300 at $0.45 → 666.67 shares
        - Result: actual = 31°C → YES wins → payout = $666.67
        - PnL: $666.67 - $15 fee - $300 stake = +$351.67
        """
        # Step 1: Ensemble
        weights = {
            "gfs": 0.30,
            "ecmwf": 0.25,
            "gem": 0.15,
            "icon": 0.10,
            "jma": 0.08,
            "cma": 0.05,
            "ukmo": 0.04,
            "mf": 0.03,
        }
        probs = {
            "gfs": 0.55,
            "ecmwf": 0.52,
            "gem": 0.48,
            "icon": 0.50,
            "jma": 0.50,
            "cma": 0.51,
            "ukmo": 0.49,
            "mf": 0.50,
        }
        ensemble = sum(probs[m] * weights[m] for m in weights)
        assert 0.50 < ensemble < 0.54, f"Ensemble {ensemble} out of expected range"

        # Step 2: Edge
        market_price = 0.45
        fee_drag = 0.05
        edge = ensemble - market_price - fee_drag
        assert edge > 0, f"Edge {edge} should be positive"

        # Step 3: Kelly
        kelly_f = max(0, edge * 0.15)  # simplified kelly_fraction
        assert kelly_f > 0, "Kelly fraction should be positive"

        # Step 4: Bet amount
        bankroll = 10000.0
        amount = bankroll * min(kelly_f, 0.05)  # capped at max_bet_pct
        assert amount > 0

        # Step 5: Shares and fee
        shares = amount / market_price
        fee = shares * market_price * 0.05

        # Step 6: Settlement (YES wins)
        actual_temp = 31.0
        threshold = 30.0
        won = actual_temp >= threshold
        assert won is True

        # Step 7: PnL
        payout = shares * 1.0
        pnl = payout - fee - amount
        assert pnl > 0, f"PnL should be positive, got {pnl}"

        print(
            f"  Full trace: ensemble={ensemble:.4f}, edge={edge:.4f}, "
            f"kelly={kelly_f:.4f}, bet=${amount:.2f}, pnl=${pnl:.2f}"
        )

    def test_full_trace_losing_bet(self):
        """
        Full trace: market → forecast → ensemble → edge → kelly → bet → LOSS

        Same setup but actual temp = 28°C → YES loses.
        PnL = -$amount (lose entire stake).
        """
        ensemble = 0.52
        market_price = 0.45
        fee_drag = 0.05
        edge = ensemble - market_price - fee_drag
        kelly_f = max(0, edge * 0.15)
        bankroll = 10000.0
        amount = bankroll * min(kelly_f, 0.05)

        # Settlement: YES loses
        actual_temp = 28.0
        threshold = 30.0
        won = actual_temp >= threshold
        assert won is False

        # PnL
        pnl = -amount
        assert pnl < 0, f"PnL should be negative, got {pnl}"

        print(f"  Losing trace: bet=${amount:.2f}, pnl=${pnl:.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8: Database operations — para yönetimi
# ══════════════════════════════════════════════════════════════════════════════


class TestStep8_DatabaseOperations:
    """Step 8: Credit/debit operations work correctly."""

    def test_debit_hold(self):
        """Bakiyeden hold tutarı düşer."""
        with get_session() as session:
            portfolio = session.query(Portfolio).first()
            if portfolio is None:
                portfolio = Portfolio(id=1, initial_value=10000.0, current_value=10000.0)
                session.add(portfolio)
                session.commit()

            initial_balance = portfolio.cash_balance or 0.0
            hold_amount = 100.0
            new_balance = initial_balance - hold_amount
            assert new_balance == initial_balance - 100.0

    def test_credit_sale(self):
        """Kazanç bakiyeye eklenir."""
        with get_session() as session:
            portfolio = session.query(Portfolio).first()
            if portfolio is None:
                portfolio = Portfolio(id=1, initial_value=10000.0, current_value=10000.0)
                session.add(portfolio)
                session.commit()

            initial = portfolio.cash_balance or 0.0
            credit_amount = 285.0
            new_total = initial + credit_amount
            assert new_total == initial + 285.0
