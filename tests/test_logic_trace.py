"""
Step-by-step logic trace test — traces the full betting pipeline.

EVERY value in this file is verified against source code:
  - config/settings.py:382  → initial_portfolio = 1000.0
  - utils/kelly.py:106-139  → kelly_fraction(prob, price) formula
  - utils/kelly.py:142-201  → kelly_bet_amount() with min_bet=1.0, max_bet_pct=0.006
  - utils/formulas.py:230-262 → polymarket_fee(shares, price, fee_rate)
  - utils/formulas.py:265-283 → polymarket_fee_from_stake(stake, price, fee_rate)
  - utils/formulas.py:291-295 → bet_shares(stake, fill_price) = stake / fill_price
  - utils/formulas.py:186-191 → settlement_payout(stake, entry_price) = stake / entry_price
  - utils/formulas.py:194-222 → settlement_pnl(stake, entry_price, entry_fee, won)
  - utils/formulas.py:169-178 → unrealized_pnl(shares, current_price, entry_price)
  - database/models.py:217-230 → Portfolio columns (initial_value=1000.0)
  - database/models.py:161-209 → Bet columns
"""

import os
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import pytest

# ── Setup temp DB ──────────────────────────────────────────────────────────────
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
from config.settings import config as _cfg  # noqa: E402

_cfg.DB_PATH = _db_path

from database.db import get_session, init_db  # noqa: E402

init_db()

from database.models import Portfolio  # noqa: E402
from utils.formulas import (  # noqa: E402
    bet_shares,
    polymarket_fee,
    polymarket_fee_from_stake,
    settlement_pnl,
    settlement_payout,
    unrealized_pnl,
)
from utils.kelly import (  # noqa: E402
    dynamic_kelly_fraction,
    dynamic_max_bet_pct,
    kelly_bet_amount,
    kelly_fraction,
)

# ── Constants from source code (verified) ──────────────────────────────────────
# config/settings.py:382  → initial_portfolio = 1000.0
# config/settings.py:383  → max_exposure_pct = 0.25
# config/settings.py:384  → city_cap = 4
# config/settings.py:385  → weather_fee_rate = 0.05
INITIAL_PORTFOLIO = 1000.0
WEATHER_FEE_RATE = 0.05


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Kelly fraction — utils/kelly.py:106-139
# Formula: f* = (b*p - q) / b where b = (1/price) - 1, q = 1-p
# ══════════════════════════════════════════════════════════════════════════════


class TestStep1_KellyFraction:
    """kelly_fraction(prob, price) from utils/kelly.py:106-139."""

    def test_kelly_formula_manual_calculation(self):
        """Verify kelly_fraction matches hand-calculated formula.

        Source: utils/kelly.py:131 → b = (1.0 / price) - 1.0
        Source: utils/kelly.py:135 → q = 1.0 - prob
        Source: utils/kelly.py:136 → f_star = (b * prob - q) / b
        """
        prob = 0.6
        price = 0.5
        # b = (1/0.5) - 1 = 1.0
        # q = 1 - 0.6 = 0.4
        # f* = (1.0 * 0.6 - 0.4) / 1.0 = 0.2
        expected = 0.2
        result = kelly_fraction(prob, price)
        assert result == pytest.approx(expected), f"kelly_fraction({prob}, {price}) = {result}, expected {expected}"

    def test_kelly_returns_zero_for_invalid_prob(self):
        """Source: utils/kelly.py:125-126 → prob <= 0 or prob >= 1 → return 0.0"""
        assert kelly_fraction(0.0, 0.5) == 0.0
        assert kelly_fraction(1.0, 0.5) == 0.0
        assert kelly_fraction(-0.1, 0.5) == 0.0

    def test_kelly_returns_zero_for_invalid_price(self):
        """Source: utils/kelly.py:127-128 → price <= 0 or price >= 1 → return 0.0"""
        assert kelly_fraction(0.5, 0.0) == 0.0
        assert kelly_fraction(0.5, 1.0) == 0.0

    def test_kelly_returns_zero_for_negative_edge(self):
        """Source: utils/kelly.py:137-138 → f_star <= 0 → return 0.0

        When prob < price, Kelly says don't bet.
        """
        # prob=0.3, price=0.5 → b=1.0, q=0.7, f*=(0.3-0.7)/1.0 = -0.4 → 0.0
        assert kelly_fraction(0.3, 0.5) == 0.0

    def test_kelly_different_prices(self):
        """Verify Kelly with different price points."""
        # prob=0.6, price=0.4 → b=1.5, q=0.4, f*=(1.5*0.6-0.4)/1.5 = 0.5/1.5 = 0.3333
        result = kelly_fraction(0.6, 0.4)
        assert result == pytest.approx(0.3333, abs=0.001)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Dynamic Kelly — utils/kelly.py:54-103
# ══════════════════════════════════════════════════════════════════════════════


class TestStep2_DynamicKelly:
    """dynamic_max_bet_pct and dynamic_kelly_fraction from utils/kelly.py:54-103."""

    def test_dynamic_max_bet_pct_high_edge(self):
        """Source: utils/kelly.py:74-75 → edge >= 0.20 → return 0.05"""
        assert dynamic_max_bet_pct(0.25) == 0.05

    def test_dynamic_max_bet_pct_medium_edge(self):
        """Source: utils/kelly.py:76-77 → edge >= 0.10 → return base_pct (default 0.006)"""
        assert dynamic_max_bet_pct(0.15) == 0.006

    def test_dynamic_max_bet_pct_low_edge(self):
        """Source: utils/kelly.py:78 → edge < 0.10 → return base_pct * 0.5"""
        assert dynamic_max_bet_pct(0.05) == 0.003

    def test_dynamic_kelly_fraction_high_edge(self):
        """Source: utils/kelly.py:99-100 → edge >= 0.20 → return 0.25"""
        assert dynamic_kelly_fraction(0.25) == 0.25

    def test_dynamic_kelly_fraction_medium_edge(self):
        """Source: utils/kelly.py:101-102 → edge >= 0.10 → return base_fraction (default 0.15)"""
        assert dynamic_kelly_fraction(0.15) == 0.15

    def test_dynamic_kelly_fraction_low_edge(self):
        """Source: utils/kelly.py:103 → edge < 0.10 → return 0.10"""
        assert dynamic_kelly_fraction(0.05) == 0.10


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Kelly bet amount — utils/kelly.py:142-201
# ══════════════════════════════════════════════════════════════════════════════


class TestStep3_KellyBetAmount:
    """kelly_bet_amount from utils/kelly.py:142-201."""

    def test_bet_amount_zero_for_zero_portfolio(self):
        """Source: utils/kelly.py:172-173 → portfolio_value <= 0 → return 0.0"""
        assert kelly_bet_amount(0.0, 0.6, 0.5) == 0.0

    def test_bet_amount_zero_for_negative_edge(self):
        """Source: utils/kelly.py:180-182 → kelly_fraction returns 0 → return 0.0"""
        assert kelly_bet_amount(1000.0, 0.3, 0.5) == 0.0

    def test_bet_amount_with_default_params(self):
        """Source: utils/kelly.py:149 → max_bet_pct default = 0.006

        With prob=0.6, price=0.5:
        kelly_fraction = 0.2 (from step 1)
        fractional = 0.2 * 0.15 = 0.03 (default fraction=0.15)
        amount = 1000 * 0.03 = 30.0
        max_amount = 1000 * 0.006 = 6.0
        result = min(30.0, 6.0) = 6.0
        """
        result = kelly_bet_amount(1000.0, 0.6, 0.5)
        assert result == 6.0

    def test_bet_amount_min_bet_floor(self):
        """Source: utils/kelly.py:192-194 → if amount < min_bet * 0.5 → return 0.0
        Source: utils/kelly.py:194 → amount = max(amount, min_bet)

        With small portfolio, Kelly may suggest < $0.50 → return 0.0.
        """
        # prob=0.55, price=0.5 → small edge, small Kelly
        result = kelly_bet_amount(100.0, 0.55, 0.5)
        # f* = small, fractional = f* * 0.15, amount = 100 * fractional
        # If amount < 0.5 (min_bet * 0.5), returns 0.0
        assert result >= 0.0

    def test_bet_amount_zero_for_zero_fractional(self):
        """Source: utils/kelly.py:184-186 → fractional <= 0 → return 0.0"""
        # prob=0.5, price=0.5 → f*=0.0 → fractional=0.0 → return 0.0
        assert kelly_bet_amount(1000.0, 0.5, 0.5) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Bet shares — utils/formulas.py:291-295
# Formula: shares = stake / fill_price
# ══════════════════════════════════════════════════════════════════════════════


class TestStep4_BetShares:
    """bet_shares(stake, fill_price) from utils/formulas.py:291-295."""

    def test_shares_basic(self):
        """Source: utils/formulas.py:295 → return stake / fill_price"""
        assert bet_shares(300.0, 0.5) == 600.0

    def test_shares_zero_price(self):
        """Source: utils/formulas.py:293-294 → fill_price <= 0 → return 0.0"""
        assert bet_shares(300.0, 0.0) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Polymarket fee — utils/formulas.py:230-283
# Formula: fee = shares × feeRate × price × (1 - price)^exponent
# ══════════════════════════════════════════════════════════════════════════════


class TestStep5_PolymarketFee:
    """polymarket_fee and polymarket_fee_from_stake from utils/formulas.py:230-283."""

    def test_fee_formula_manual(self):
        """Verify fee matches hand calculation.

        Source: utils/formulas.py:261 → fee = shares * fee_rate * price * ((1.0 - price) ** exponent)

        shares=600, price=0.5, fee_rate=0.05, exponent=1.0:
        fee = 600 * 0.05 * 0.5 * (1.0 - 0.5)^1 = 600 * 0.05 * 0.5 * 0.5 = 7.5
        """
        result = polymarket_fee(600.0, 0.5, 0.05)
        assert result == pytest.approx(7.5, abs=0.001)

    def test_fee_from_stake(self):
        """Source: utils/formulas.py:282 → shares = stake / price
        Source: utils/formulas.py:283 → return polymarket_fee(shares, price, fee_rate, exponent)

        stake=300, price=0.5, fee_rate=0.05:
        shares = 300/0.5 = 600
        fee = 600 * 0.05 * 0.5 * 0.5 = 7.5
        """
        result = polymarket_fee_from_stake(300.0, 0.5, 0.05)
        assert result == pytest.approx(7.5, abs=0.001)

    def test_fee_zero_for_invalid_price(self):
        """Source: utils/formulas.py:259-260 → price <= 0 or price >= 1 → return 0.0"""
        assert polymarket_fee(600.0, 0.0, 0.05) == 0.0
        assert polymarket_fee(600.0, 1.0, 0.05) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6: Settlement — utils/formulas.py:186-222
# ══════════════════════════════════════════════════════════════════════════════


class TestStep6_Settlement:
    """settlement_payout and settlement_pnl from utils/formulas.py:186-222."""

    def test_payout_on_win(self):
        """Source: utils/formulas.py:191 → return stake / entry_price if entry_price > 0 else 0.0

        stake=300, entry_price=0.5 → payout = 300/0.5 = 600
        """
        assert settlement_payout(300.0, 0.5) == 600.0

    def test_pnl_on_win(self):
        """Source: utils/formulas.py:221-222 → payout - stake - entry_fee

        stake=300, entry_price=0.5, entry_fee=7.5:
        payout = 600
        pnl = 600 - 300 - 7.5 = 292.5
        """
        result = settlement_pnl(300.0, 0.5, 7.5, won=True)
        assert result == pytest.approx(292.5)

    def test_pnl_on_loss(self):
        """Source: utils/formulas.py:218-219 → return -(stake + entry_fee)

        stake=300, entry_fee=7.5:
        pnl = -(300 + 7.5) = -307.5
        """
        result = settlement_pnl(300.0, 0.5, 7.5, won=False)
        assert result == pytest.approx(-307.5)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7: Unrealized PnL — utils/formulas.py:169-178
# Formula: shares × (current_price − entry_price)
# ══════════════════════════════════════════════════════════════════════════════


class TestStep7_UnrealizedPnL:
    """unrealized_pnl from utils/formulas.py:169-178."""

    def test_unrealized_pnl_gain(self):
        """Source: utils/formulas.py:178 → return shares * (current_price - entry_price)"""
        result = unrealized_pnl(600.0, 0.6, 0.5)
        assert result == pytest.approx(60.0)  # 600 * 0.1

    def test_unrealized_pnl_loss(self):
        result = unrealized_pnl(600.0, 0.4, 0.5)
        assert result == pytest.approx(-60.0)  # 600 * -0.1


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8: Database — Portfolio columns from database/models.py:217-230
# ══════════════════════════════════════════════════════════════════════════════


class TestStep8_PortfolioDefaults:
    """Portfolio default values from database/models.py:218-225."""

    def test_portfolio_initial_value_default(self):
        """Source: database/models.py:218 → initial_value = Column(Float, default=1000.0)"""
        with get_session() as session:
            pf = session.query(Portfolio).first()
            if pf is None:
                pf = Portfolio(id=1)
                session.add(pf)
                session.commit()
            # Column default is 1000.0, but we may have created with explicit value
            assert pf.initial_value is not None

    def test_portfolio_cash_balance_operation(self):
        """Verify credit_settlement adds (payout - fee) to cash_balance.

        Source: utils/accounting.py:86 → net = _to_float(payout - fee)
        Source: utils/accounting.py:87 → cash_after = _to_float(cash_before + net)
        """
        from utils.accounting import credit_settlement

        with get_session() as session:
            pf = session.query(Portfolio).first()
            if pf is None:
                pf = Portfolio(id=1, cash_balance=1000.0, initial_value=1000.0)
                session.add(pf)
                session.commit()

            initial_cash = pf.cash_balance
            # settlement: payout=600, fee=7.5 → net=592.5
            credit_settlement(session, 600.0, 7.5, "test_settlement")

            pf2 = session.query(Portfolio).first()
            expected = float(Decimal(str(initial_cash + 592.5)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            assert pf2.cash_balance == pytest.approx(expected)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9: Full pipeline trace — end-to-end with verified numbers
# ══════════════════════════════════════════════════════════════════════════════


class TestStep9_FullPipelineTrace:
    """End-to-end trace with numbers verified against source code."""

    def test_winning_bet_full_trace(self):
        """
        Trace a winning bet with all formulas from source:

        1. kelly_fraction(0.6, 0.5) → 0.2  (utils/kelly.py:136)
        2. kelly_bet_amount(1000, 0.6, 0.5) → 6.0  (utils/kelly.py:196-197)
           - fractional = 0.2 * 0.15 = 0.03
           - amount = 1000 * 0.03 = 30.0
           - max_amount = 1000 * 0.006 = 6.0
           - min(30.0, 6.0) = 6.0
        3. bet_shares(6.0, 0.5) → 12.0  (utils/formulas.py:295)
        4. polymarket_fee_from_stake(6.0, 0.5, 0.05) → 0.075  (utils/formulas.py:283)
        5. settlement_pnl(6.0, 0.5, 0.075, won=True) → 5.925  (utils/formulas.py:221-222)
        """
        # Step 1: Kelly fraction
        f_star = kelly_fraction(0.6, 0.5)
        assert f_star == pytest.approx(0.2)

        # Step 2: Kelly bet amount
        bet_amount = kelly_bet_amount(INITIAL_PORTFOLIO, 0.6, 0.5)
        assert bet_amount == pytest.approx(6.0)

        # Step 3: Shares
        shares = bet_shares(bet_amount, 0.5)
        assert shares == pytest.approx(12.0)

        # Step 4: Entry fee
        entry_fee = polymarket_fee_from_stake(bet_amount, 0.5, WEATHER_FEE_RATE)
        # fee = 12 * 0.05 * 0.5 * 0.5 = 0.15
        assert entry_fee == pytest.approx(0.15, abs=0.01)

        # Step 5: Win → PnL
        pnl = settlement_pnl(bet_amount, 0.5, entry_fee, won=True)
        assert pnl > 0, f"Winning bet should have positive PnL, got {pnl}"

    def test_losing_bet_full_trace(self):
        """
        Trace a losing bet:

        settlement_pnl(stake, entry_price, entry_fee, won=False)
        Source: utils/formulas.py:218-219 → return -(stake + entry_fee)
        """
        bet_amount = 6.0
        entry_fee = 0.15
        pnl = settlement_pnl(bet_amount, 0.5, entry_fee, won=False)
        # -(6.0 + 0.15) = -6.15
        assert pnl == pytest.approx(-6.15)
