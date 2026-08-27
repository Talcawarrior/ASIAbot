"""Background bot loops: scan-and-bet, settlement, stale cleanup.

ASYNCIO safety: Each loop has a SINGLE try/except wrapping the entire body
so that no exception can silently kill the loop without logging.

Watchdog: settlement_loop monitors scan_loop health via state.last_scan.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from database.db import get_session
from database.models import OPEN_BET_STATUSES, Bet, WeatherMarket

logger = logging.getLogger("BOT_LOOP")

# Timeout values (seconds)
_FETCH_TIMEOUT = 180
_CYCLE_TIMEOUT = 600
_CLEANUP_TIMEOUT = 60

# Scan intervals (seconds)
_FAST_SCAN_INTERVAL = 60  # 1 MINUTE - FAST MODE
_NORMAL_SCAN_INTERVAL = 300  # 5 MINUTES - NORMAL MONITORING
_WEATHER_FETCH_INTERVAL = 3600  # 1 HOUR for Open-Meteo

# Watchdog thresholds (seconds) — junbo degerleri, asiri tolerans
_WATCHDOG_WARNING = 900  # 15 minutes - warning
_WATCHDOG_DEAD = 1800  # 30 minutes - dead
_WATCHDOG_RESTART = 3600  # 1 hour - restart


def _get_market_count() -> int:
    with get_session() as db:
        return db.query(WeatherMarket).filter(WeatherMarket.status == "open").count()


def _is_midnight_window(now: datetime) -> bool:
    from config.settings import bot_config

    window_minutes = bot_config.midnight_scan_window
    return now.hour == 0 and now.minute < window_minutes


def _get_open_target_dates() -> set:
    """Return set of open market calendar dates (date objects)."""
    from database.db import get_session
    from database.models import WeatherMarket

    with get_session() as session:
        rows = (
            session.query(WeatherMarket.target_date)
            .filter(
                WeatherMarket.status == "open",
                WeatherMarket.latitude != 0,
                WeatherMarket.longitude != 0,
            )
            .all()
        )
        dates = set()
        for (td,) in rows:
            if td:
                dates.add(td.date())
        return dates


def _get_open_market_count_for_date(target_date) -> int:
    """Return count of open markets for a specific calendar date."""
    with get_session() as session:
        return (
            session.query(WeatherMarket)
            .filter(
                WeatherMarket.status == "open",
                WeatherMarket.target_date >= target_date,
                WeatherMarket.target_date < target_date + timedelta(days=1),
                WeatherMarket.latitude != 0,
                WeatherMarket.longitude != 0,
            )
            .count()
        )


def _next_two_day_target(last_max_date, open_dates):
    """Pure function: returns the next 2-day-ahead target date if it just opened.

    Returns the date if max(open_dates) > last_max_date (meaning a new 2-day-ahead
    date just opened), otherwise returns None. Only triggers once per date.
    """
    if not open_dates:
        return None
    max_open = max(open_dates)
    if last_max_date is None or max_open > last_max_date:
        return max_open
    return None


def _get_scan_interval(now: datetime, fast_mode_until: datetime | None) -> int:
    """Return scan interval in seconds based on mode."""
    if fast_mode_until and now < fast_mode_until:
        return 60  # 1 minute fast mode
    if _is_midnight_window(now):
        return 60  # 1 minute at midnight
    return 300  # 5 minutes normal


async def scan_and_bet_loop(state):
    """Scan loop with date-based fast-mode trigger.

    Logic:
    - Baseline: max open target date at startup
    - Every 5 min: fetch Polymarket, check if max open date advanced (meaning 2-day-ahead markets opened)
    - If max open date advanced -> FAST MODE for 30 min (1 min intervals)
    - Normal: 5 min interval
    - Fast mode: 30 min duration, 1 min intervals
    - Weather fetch: hourly (cached)
    """
    from jobs.scheduler import (
        run_cycle,
        run_fetch_markets,
        run_fetch_weather,
        run_parse_markets,
    )

    # Initialize baseline: max open target date at startup
    open_dates = _get_open_target_dates()
    baseline_max_date = max(open_dates) if open_dates else None
    logger.info("Baseline max open date: %s", baseline_max_date)

    fast_mode_until = None
    last_day = None

    while state.is_running:
        try:
            state.last_scan = datetime.now(timezone.utc).replace(tzinfo=None)
            scan_start = datetime.now(timezone.utc)

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            today = now.date()
            is_new_day = last_day is not None and today != last_day
            last_day = today

            if is_new_day:
                logger.info("Midnight detected - running immediate scan")

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

            # STEP 1: Fetch Polymarket markets (EVERY CYCLE)
            from jobs.scheduler import run_fetch_markets

            await asyncio.wait_for(asyncio.to_thread(run_fetch_markets), timeout=180)

            # Check if 2-day-ahead markets just opened
            open_dates = _get_open_target_dates()
            current_max = max(open_dates) if open_dates else None

            if baseline_max_date is None:
                # First run: initialize baseline
                baseline_max_date = current_max
                logger.info("Baseline max open date initialized: %s", baseline_max_date)
            elif current_max and current_max > baseline_max_date:
                # New 2-day-ahead markets just opened!
                baseline_max_date = current_max
                fast_mode_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30)
                logger.info(
                    "2-day-ahead date %s opened (%d markets) — price poller FAST (1min) for 30 min",
                    current_max,
                    _get_open_market_count_for_date(current_max),
                )

            # Weather fetch: every cycle, but only for markets missing forecasts
            from jobs.scheduler import run_fetch_weather, run_parse_markets

            await asyncio.gather(
                asyncio.to_thread(run_parse_markets),
                asyncio.to_thread(run_fetch_weather),
            )

            # Analyze + bet + risk
            from jobs.scheduler import run_cycle

            await asyncio.to_thread(run_cycle)

            # Determine next interval
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            in_fast_mode = fast_mode_until and now_utc < fast_mode_until
            interval = 60 if in_fast_mode else 300
            mode = "FAST" if in_fast_mode else "NORMAL"
            logger.info(
                "Scan completed in %.1fs [%s mode], next in %ds",
                (datetime.now(timezone.utc) - datetime.fromisoformat(str(scan_start))).total_seconds(),
                mode,
                interval,
            )
            state.last_scan = datetime.now(timezone.utc).replace(tzinfo=None)

            await asyncio.sleep(60 if in_fast_mode else 300)

        except asyncio.CancelledError:
            logger.info("Scan loop cancelled - shutting down")
            break
        except asyncio.TimeoutError:
            logger.error("Scan step timed out - retry in 60s")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error("Scan error: %s - retry in 60s", e, exc_info=True)
            await asyncio.sleep(60)

    logger.info("Scan loop exited (is_running=%s)", state.is_running)


async def settlement_loop(state):
    """Settlement loop + scan loop watchdog."""
    from jobs.scheduler import run_settle

    last_cleanup_date = None
    scan_healthy = True

    while state.is_running:
        try:
            # Watchdog: scan loop health check
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if state.last_scan:
                elapsed = (now_utc - state.last_scan).total_seconds()
                if elapsed > _WATCHDOG_WARNING:
                    if scan_healthy:
                        logger.warning(
                            "SCAN LOOP WATCHDOG: No scan for %.1f minutes! last_scan=%s", elapsed / 60, state.last_scan
                        )
                    scan_healthy = False
                    if elapsed > _WATCHDOG_DEAD:
                        logger.warning("SCAN LOOP WATCHDOG: Last scan %.1f min ago (warning)", elapsed / 60)
                    if elapsed > _WATCHDOG_RESTART:
                        logger.critical("SCAN LOOP DEAD for >%.0f min - stopping bot for restart", elapsed / 60)
                        state.is_running = False
                        break
                else:
                    if not scan_healthy:
                        logger.info("Scan loop recovered - healthy again")
                    scan_healthy = True
            else:
                scan_healthy = False

            # Normal settlement
            await asyncio.to_thread(run_settle)

            # Stale bet cleanup: 48h+ past target_date → cancel + refund (dead code fix)
            try:
                await asyncio.to_thread(_cleanup_stale_bets)
            except Exception as e:
                logger.warning("Stale cleanup error: %s", e)

            today = datetime.now(timezone.utc).date()
            if last_cleanup_date != today:
                from database.db_cleanup import auto_cleanup

                await asyncio.to_thread(auto_cleanup, hot_days=10, cold_days=120)
                last_cleanup_date = today

            if state.sia_loop is not None and (
                state.sia_last_run is None
                or (now_utc - state.sia_last_run).total_seconds() >= state.sia_interval_hours * 3600
            ):
                await asyncio.to_thread(state.sia_loop.run_optimization_cycle)
                state.sia_last_run = datetime.now(timezone.utc).replace(tzinfo=None)

        except asyncio.CancelledError:
            logger.info("Settlement loop cancelled")
            break
        except Exception as e:
            logger.error("Settle error: %s", e, exc_info=True)

        await asyncio.sleep(60)

    logger.info("Settlement loop exited (is_running=%s)", state.is_running)


async def forecast_collector_loop(state):
    """t0/t1/t2 collector - Windows 24h background.

    8 VC key ile 8000/gun = saatlik 64 sehir x3 gun=192 kayit x24=4608 <8000.
    Her saat 1 key rotasyonla toplanir, WeatherAPI/OpenWeather 6 saatte bir
    (1000/gun limit). Wethr.net/polyweather yok.
    """
    while state.is_running:
        try:
            from data_pipeline.t_horizon_collector import collect_once

            await asyncio.to_thread(collect_once)
            logger.info("forecast_collector: t0/t1/t2 toplandi (8 VC key rotasyon)")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("forecast_collector error: %s", e, exc_info=True)
        # 8 key ile saatlik toplama mumkun (192*24=4608 <8000)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            break
    logger.info("forecast_collector loop exited")


async def t_horizon_report_loop(state):
    """Gun sonu WU uyumu raporu - her gun 00:30 UTC'de dun'un actual'ini doldur."""
    last_report_date = None
    while state.is_running:
        try:
            now = datetime.now(timezone.utc)
            # 00:30 UTC'yi bekle
            if now.hour == 0 and now.minute >= 30 and last_report_date != now.date():
                from data_pipeline.t_horizon_report import run_daily_job

                report = await asyncio.to_thread(run_daily_job)
                logger.info("t_horizon_report:\n%s", report)
                last_report_date = now.date()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("t_horizon_report error: %s", e, exc_info=True)
        try:
            await asyncio.sleep(600)  # 10 dk kontrol
        except asyncio.CancelledError:
            break
    logger.info("t_horizon_report loop exited")


def _cleanup_stale_bets():
    from sqlalchemy import func
    from utils.formulas import portfolio_total_value

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        stale = (
            session.query(Bet)
            .filter(
                Bet.status.in_(OPEN_BET_STATUSES),
                Bet.placed_at < cutoff,
            )
            .all()
        )
        cancelled = 0
        for bet in stale:
            market = session.query(WeatherMarket).filter(WeatherMarket.id == bet.market_id).first()
            should_cancel = False
            if not market:
                should_cancel = True
            elif market.target_date and (now - market.target_date).total_seconds() > 48 * 3600:
                should_cancel = True

            if should_cancel:
                from utils.accounting import credit_sale

                # Ladder-aware refund: only filled rungs were debited
                import json as _json

                ladder = []
                try:
                    if bet.ladder_data:
                        ladder = _json.loads(bet.ladder_data) if isinstance(bet.ladder_data, str) else bet.ladder_data
                except Exception:
                    ladder = []
                if ladder and isinstance(ladder, list):
                    filled_amount = sum(float(r.get("amount", 0)) for r in ladder if r.get("status") == "filled")
                    refund_amount = filled_amount if filled_amount > 0 else float(bet.amount or 0)
                else:
                    refund_amount = float(bet.amount or 0)
                bet.status = "cancelled"
                bet.settled_at = now
                bet.closed_at = now
                bet.close_reason = "stale_cleanup"
                bet.unrealized_pnl = 0.0
                if refund_amount > 0:
                    credit_sale(session, refund_amount, f"stale_cleanup:bet_{bet.id}")
                cancelled += 1

        if cancelled > 0:
            # Sync portfolio book value after refunds
            from database.models import Portfolio

            pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
            if pf is not None:
                open_exp = (
                    session.query(func.coalesce(func.sum(Bet.amount), 0.0))
                    .filter(Bet.status.in_(OPEN_BET_STATUSES))
                    .scalar()
                    or 0.0
                )
                pf.total_value = portfolio_total_value(float(pf.cash_balance or 0.0), float(open_exp))
                pf.current_value = pf.total_value
                pf.last_updated = now
            session.commit()
            logger.info("Stale cleanup: cancelled %d old bets (>48h past target)", cancelled)
