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
_FAST_SCAN_INTERVAL = 60          # 1 MINUTE - FAST MODE
_NORMAL_SCAN_INTERVAL = 300       # 5 MINUTES - NORMAL MONITORING
_WEATHER_FETCH_INTERVAL = 3600    # 1 HOUR for Open-Meteo

# Watchdog thresholds (seconds)
_WATCHDOG_WARNING = 120     # 2 minutes - warning
_WATCHDOG_DEAD = 300        # 5 minutes - dead
_WATCHDOG_RESTART = 600     # 10 minutes - restart


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
        rows = session.query(WeatherMarket.target_date).filter(
            WeatherMarket.status == "open",
            WeatherMarket.latitude != 0,
            WeatherMarket.longitude != 0,
        ).all()
        dates = set()
        for (td,) in rows:
            if td:
                dates.add(td.date())
        return dates


def _get_open_market_count_for_date(target_date) -> int:
    """Return count of open markets for a specific calendar date."""
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    with get_session() as session:
        return session.query(WeatherMarket).filter(
            WeatherMarket.status == "open",
            WeatherMarket.target_date >= target_date,
            WeatherMarket.target_date < target_date + timedelta(days=1),
            WeatherMarket.latitude != 0,
            WeatherMarket.longitude != 0,
        ).count()


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
    from config.settings import bot_config
    if _is_midnight_window(now):
        return 60  # 1 minute at midnight
    return 300  # 5 minutes normal


def _is_midnight_window(now: datetime) -> bool:
    from config.settings import bot_config
    window_minutes = bot_config.midnight_scan_window
    return now.hour == 0 and now.minute < window_minutes


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

    stale_check_counter = 0
    last_weather_fetch = None
    fast_mode_until = None

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

            if current_max and current_max > baseline_max_date:
                # New 2-day-ahead markets just opened!
                baseline_max_date = current_max
                fast_mode_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30)
                logger.info(
                    "2-day-ahead date %s opened (%d markets) — price poller FAST (1min) for 30 min",
                    current_max, _get_open_market_count_for_date(current_max)
                )

            # Weather fetch (hourly)
            if last_weather_fetch is None or (datetime.now(timezone.utc) - last_weather_fetch).total_seconds() >= 3600:
                logger.info("Weather fetch triggered")
                from jobs.scheduler import run_fetch_weather, run_parse_markets
                await asyncio.gather(
                    asyncio.to_thread(run_parse_markets),
                    asyncio.to_thread(run_fetch_weather),
                )
            else:
                # Parse only
                from jobs.scheduler import run_parse_markets
                await asyncio.to_thread(run_parse_markets)

            # Analyze + bet + risk
            from jobs.scheduler import run_cycle
            await asyncio.to_thread(run_cycle)

            # Determine next interval
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            in_fast_mode = fast_mode_until and now_utc < fast_mode_until
            interval = 60 if in_fast_mode else 300
            mode = "FAST" if in_fast_mode else "NORMAL"
            logger.info("Scan completed in %.1fs [%s mode], next in %ds", 
                        (datetime.now(timezone.utc) - datetime.fromisoformat(str(scan_start))).total_seconds(), mode, interval)

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
                if elapsed > 120:  # 2 minutes - warning
                    if scan_healthy:
                        logger.error(
                            "SCAN LOOP WATCHDOG: No scan for %.1f minutes! last_scan=%s",
                            elapsed / 60, state.last_scan
                        )
                    scan_healthy = False
                    if elapsed > 300:  # 5 minutes - restart
                        logger.critical(
                            "SCAN LOOP DEAD for >5 min - stopping bot for restart"
                        )
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


def _cleanup_stale_bets():
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
                bet.status = "cancelled"
                bet.settled_at = now
                bet.close_reason = "stale_cleanup"
                amount = float(bet.amount or 0)
                if amount > 0:
                    credit_sale(session, amount, f"stale_cleanup:bet_{bet.id}")
                cancelled += 1

        if cancelled > 0:
            session.commit()
            logger.info("Stale cleanup: cancelled %d old bets", cancelled)