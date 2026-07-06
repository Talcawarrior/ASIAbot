"""Central financial formulas — single source of truth for ALL calculations.

Every caller MUST import from here instead of re-implementing the formula.
If the math changes, change it here — it propagates everywhere.

Formula inventory:
  1. max_bet_cap              — per-bet dollar ceiling
  2. conservative_value       — portfolio basis that excludes today's unrealized gains
  3. max_exposure             — total open-position ceiling
  4. unrealized_pnl           — per-bet paper PnL
  5. settlement_pnl           — per-bet realised PnL (Polymarket win/loss)
  6. polymarket_fee           — C × feeRate × p × (1-p)  (official)
  7. polymarket_fee_from_stake — stake × feeRate × (1-p)  (shortcut)
  8. settlement_payout        — gross payout when winning
  9. portfolio_total          — cash + open_exposure (book value)
  10. portfolio_current       — initial + all PnL (market value, includes unrealised)
  11. roi_pct                 — return on stake
  12. win_rate_pct            — wins / closed
  13. daily_pnl               — today's profit / loss
  14. bet_shares              — stake / price (shares purchased)
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fee schedule — live from Gamma API with in-memory cache
# ---------------------------------------------------------------------------

# Cache: { "condition_id": {"rate": float, "exponent": float, "takerOnly": bool, "rebateRate": float, "_ts": float} }
_fee_schedule_cache: dict[str, dict[str, Any]] = {}
_FEE_CACHE_TTL = 3600  # 1 hour


def get_fee_schedule(condition_id: str | None = None) -> dict[str, Any]:
    """Fetch fee schedule from Gamma API for a given market.

    Returns dict with keys: rate, exponent, takerOnly, rebateRate.
    Defaults to Weather rate (0.05, exponent=1) if API fails or condition_id is None.

    Caches results for 1 hour in-memory to avoid hammering the API.
    """
    from config.settings import bot_config

    defaults = {
        "rate": bot_config.weather_fee_rate,
        "exponent": 1.0,
        "takerOnly": True,
        "rebateRate": 0.25,
    }

    if condition_id is None:
        return defaults

    # Check cache
    cached = _fee_schedule_cache.get(condition_id)
    if cached and (time.time() - cached.get("_ts", 0)) < _FEE_CACHE_TTL:
        return cached

    # Fetch from API
    try:
        import requests as _req

        resp = _req.get(
            f"https://gamma-api.polymarket.com/markets/{condition_id}",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            schedule = data.get("feeSchedule") or {}
            if schedule:
                result = {
                    "rate": float(schedule.get("rate", defaults["rate"])),
                    "exponent": float(schedule.get("exponent", defaults["exponent"])),
                    "takerOnly": schedule.get("takerOnly", defaults["takerOnly"]),
                    "rebateRate": float(schedule.get("rebateRate", defaults["rebateRate"])),
                    "_ts": time.time(),
                }
                _fee_schedule_cache[condition_id] = result
                return result
    except Exception as e:
        logger.debug("Fee schedule fetch failed for %s: %s", condition_id, e)

    return defaults


def clear_fee_cache() -> None:
    """Clear the fee schedule cache (e.g. on config reload)."""
    _fee_schedule_cache.clear()


# ---------------------------------------------------------------------------
# 1. Max bet per position
# ---------------------------------------------------------------------------


def max_bet_cap(conservative_value: float, max_bet_pct: float) -> float:
    """Per-bet dollar ceiling = conservative_value × MAX_EXPOSURE_PCT × max_bet_pct.

    conservative_value = initial capital + realized PnL (bets closed before today).
    This ensures max_bet is proportional to the daily risk budget (exposure cap),
    not the full market-value portfolio.

    Essentially: max_bet_cap = exposure_cap × max_bet_pct
    where exposure_cap = conservative_value × MAX_EXPOSURE_PCT.

    Used by:
      - calculator.py (:284, :296) — Kelly sizing
      - bet_placer.py (:242)       — Cap 1 hard ceiling
    """
    from config.settings import Config

    daily_limit = conservative_value * Config.MAX_EXPOSURE_PCT
    return daily_limit * max_bet_pct


# ---------------------------------------------------------------------------
# 2. Conservative portfolio value (initial + realised closed before today)
# ---------------------------------------------------------------------------


def conservative_portfolio_value(initial_capital: float, realized_before_today: float) -> float:
    """Portfolio basis that prevents the feedback loop.

    Only counts:
      - initial capital
      - PnL from bets that CLOSED before today (realised)

    Excludes:
      - today's realised PnL (would inflate today's cap)
      - unrealised PnL (paper money)

    Used by:
      - strategy.py (_conservative_portfolio_value, check_exposure_cap)
      - main.py (:340)  — API max_exposure
      - bet_placer.py   — Cap 2 log
    """
    return initial_capital + realized_before_today


# ---------------------------------------------------------------------------
# 3. Max total exposure (sum of all open bet amounts)
# ---------------------------------------------------------------------------


def max_exposure_cap(initial_capital: float, realized_before_today: float, total_exposure_pct: float) -> float:
    """Total open-position ceiling.

    Formula: (initial + realized_before_today) × TOTAL_EXPOSURE_PCT

    Used by:
      - strategy.py (check_exposure_cap, calculate_position_size*)
      - main.py     (API /api/status → portfolio.max_exposure)
      - bet_placer.py (Cap 2)
    """
    return conservative_portfolio_value(initial_capital, realized_before_today) * total_exposure_pct


# ---------------------------------------------------------------------------
# 4. Unrealised PnL per bet
# ---------------------------------------------------------------------------


def unrealized_pnl(shares: float, current_price: float, entry_price: float) -> float:
    """Paper profit / loss on an open position.

    shares × (current_price − entry_price)

    Used by:
      - scheduler.py (:137)  — run_price_update
      - frontend (api.ts:462) — open positions display
    """
    return shares * (current_price - entry_price)


# ---------------------------------------------------------------------------
# 5. Settlement PnL (Polymarket win / loss)
# ---------------------------------------------------------------------------


def settlement_payout(stake: float, entry_price: float) -> float:
    """Gross payout when a bet wins: stake / entry_price.

    Used by settler.py for credit_settlement accounting.
    """
    return stake / entry_price if entry_price > 0 else 0.0


def settlement_pnl(stake: float, entry_price: float, entry_fee: float, won: bool) -> float:
    """Realised PnL when Polymarket resolves a bet.

    According to Polymarket's official fee model:
      fee = C × feeRate × p × (1-p)

    The fee is charged at **trade match time** (entry), NOT at settlement.
    At settlement the outcome share price is $1.00 (won) or $0.00 (lost),
    so p × (1-p) = 0 — settlement fee is mathematically zero.

    When won:
      payout       = stake / entry_price      (= shares × $1.00)
      settlement_fee = 0                      (mathematical: p→1 ⇒ p(1-p)→0)
      net_pnl      = payout − stake − entry_fee

    When lost:
      net_pnl      = −stake − entry_fee       (stake + fee already paid)

    entry_fee is calculated at bet placement time and stored in Bet.entry_fee.
    See polymarket_fee() / polymarket_fee_from_stake() in this module.

    Used by:
      - settler.py   — _settle_market_resolution
    """
    if not won:
        return -(stake + entry_fee)

    payout = settlement_payout(stake, entry_price)
    return payout - stake - entry_fee


# ---------------------------------------------------------------------------
# 6. Polymarket taker fee — official formula
# ---------------------------------------------------------------------------


def polymarket_fee(
    shares: float,
    price: float,
    fee_rate: float,
    exponent: float = 1.0,
) -> float:
    """Polymarket taker fee at trade match time.

    Official formula (per docs.polymarket.com/trading/fees):
      fee = C × feeRate × p × (1-p)^exponent

    Where:
      C        = number of shares traded
      feeRate  = category rate (Weather = 0.05, Crypto = 0.07, etc.)
      p        = trade price (0.01–0.99)
      exponent = category exponent (Weather=1, may change in future)

    Fee is collected at order match time, NOT at market settlement.
    Settlement fee is always zero (p→1 ⇒ p(1-p)→0).

    Rounding: 5 decimal places, minimum 0.00001 USDC.

    This is the canonical implementation. All fee calculations go through this.

    Used by:
      - scheduler.py (:301)  — early-exit fee
      - backtest_simulator.py — backtest fee
      - karpathy_weekly.py   — ISA-Karpathy fee
    """
    if price <= 0 or price >= 1:
        return 0.0
    fee = shares * fee_rate * price * ((1.0 - price) ** exponent)
    return round(fee, 5) if fee >= 0.00001 else 0.0


def polymarket_fee_from_stake(
    stake: float,
    price: float,
    fee_rate: float,
    exponent: float = 1.0,
) -> float:
    """Stake-based shortcut for polymarket_fee.

    Since shares = stake / price, we delegate to polymarket_fee() for
    consistency. Both functions now use the same canonical formula:
      fee = C × feeRate × p × (1-p)^exponent

    Used by:
      - bet_placer.py — entry_fee at bet creation time
    """
    if price <= 0:
        return 0.0
    shares = stake / price
    return polymarket_fee(shares, price, fee_rate, exponent)


# ---------------------------------------------------------------------------
# 7. Shares purchased
# ---------------------------------------------------------------------------


def bet_shares(stake: float, fill_price: float) -> float:
    """Number of outcome shares the stake buys at the given fill price."""
    if fill_price <= 0:
        return 0.0
    return stake / fill_price


# ---------------------------------------------------------------------------
# 8. Portfolio book value (accounting view)
# ---------------------------------------------------------------------------


def portfolio_total_value(cash_balance: float, open_exposure: float) -> float:
    """Book value: cash on hand + stakes locked in open bets.

    Excludes unrealised PnL (paper gains/losses).

    Used by:
      - scheduler.py (:200)  — run_price_update
      - settler.py   (:99)   — post-settlement sync
    """
    return round(cash_balance + open_exposure, 2)


# ---------------------------------------------------------------------------
# 9. Portfolio market value (dashboard view)
# ---------------------------------------------------------------------------


def portfolio_current_value(initial_capital: float, realized_pnl: float, unrealized_pnl: float) -> float:
    """Market value: initial + all PnL (includes unrealised paper gains).

    Used by:
      - main.py      (:332)  — API /api/status → portfolio.current
      - frontend     (api.ts:350, :391, :416)
    """
    return initial_capital + realized_pnl + unrealized_pnl


# ---------------------------------------------------------------------------
# 10. ROI percentage
# ---------------------------------------------------------------------------


def roi_pct(pnl: float, stake: float) -> float:
    """Return on investment as a percentage.

    ROI = (pnl / stake) × 100

    Used by:
      - main.py (:282, :855, :904)
      - API trade-history and health stats
    """
    if stake <= 0:
        return 0.0
    return (pnl / stake) * 100


# ---------------------------------------------------------------------------
# 11. Win rate
# ---------------------------------------------------------------------------


def win_rate_pct(wins: int, total_closed: int) -> float:
    """Win rate as a percentage.

    win_rate = (wins / total_closed) × 100

    Used by:
      - main.py (:898, :1307, :1363)
    """
    if total_closed <= 0:
        return 0.0
    return (wins / total_closed) * 100


# ---------------------------------------------------------------------------
# 12. Daily PnL
# ---------------------------------------------------------------------------


def daily_pnl(today_realized: float, open_bets: list) -> float:
    """Today's total PnL = realised today + sum(unrealised on open bets).

    Used by:
      - main.py (:293)  — API daily_pnl
    """
    unrealized_total = sum(getattr(b, "unrealized_pnl", 0) or 0 for b in open_bets)
    return today_realized + float(unrealized_total)


# ---------------------------------------------------------------------------
# 13. (removed) exit_price_from_pnl — HATA-16 FIX
# ---------------------------------------------------------------------------
# Bu fonksiyon artik kullanilmiyor (dead code). Frontend zaten backend'den
# gelen exit_price (bet.current_price) kullaniyor. Onceki Python docstring
# YES/NO bazliydi, frontend fallback WIN/LOSS bazliydi — capisma vardi.
