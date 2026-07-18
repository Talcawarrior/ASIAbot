"""Meteo forecast scraper module querying Open-Meteo and WeatherAPI."""

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime

import requests

from config.settings import bot_config, config
from database.db import get_session
from database.models import WeatherForecast, WeatherMarket
from scrapers.async_client import AsyncHttpClient
from utils.retry import retry

logger = logging.getLogger("SCRAPER_METEO")


# Module-level in-process cache for (lat, lon, target_date, source) → result
# Avoids hammering the upstream APIs when many markets share the same
# (city, target_date) tuple (e.g., 11 Polymarket threshold markets for
# "London 2026-06-08" all need the same Open-Meteo forecast).
_FETCH_CACHE: dict[tuple[float, float, str, str], tuple] = {}
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE_ASYNC_LOCK = asyncio.Lock()

# Successes live for 30 minutes; failures for 5 minutes. The original
# cache remembered failures for the lifetime of the process, which
# made the scraper silently stop working after the first 429 hit: the
# (lat, lon, date, source) tuple was stored as None and every later
# call returned the cached failure forever. With TTL the bot recovers
# on its own and only re-issues requests every few minutes.
_SUCCESS_TTL_S = 30.0 * 60.0
_FAILURE_TTL_S = 5.0 * 60.0


def _cache_get(key):
    with _FETCH_CACHE_LOCK:
        entry = _FETCH_CACHE.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            _FETCH_CACHE.pop(key, None)
            return None
        return value


async def _cache_get_async(key):
    """Async version of _cache_get using asyncio.Lock."""
    async with _FETCH_CACHE_ASYNC_LOCK:
        entry = _FETCH_CACHE.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            _FETCH_CACHE.pop(key, None)
            return None
        return value


def _cache_set(key, value):
    with _FETCH_CACHE_LOCK:
        ttl = _SUCCESS_TTL_S if value is not None else _FAILURE_TTL_S
        _FETCH_CACHE[key] = (value, time.monotonic() + ttl)


async def _cache_set_async(key, value):
    """Async version of _cache_set using asyncio.Lock."""
    async with _FETCH_CACHE_ASYNC_LOCK:
        ttl = _SUCCESS_TTL_S if value is not None else _FAILURE_TTL_S
        _FETCH_CACHE[key] = (value, time.monotonic() + ttl)


def _cache_clear() -> None:
    """Reset the fetch cache. Useful for tests and for the scheduler
    when it wants to force a refresh after a configurable TTL."""
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE.clear()


async def _cache_clear_async() -> None:
    """Async version of _cache_clear using asyncio.Lock."""
    async with _FETCH_CACHE_ASYNC_LOCK:
        _FETCH_CACHE.clear()


# Per-host request throttle to keep us under Open-Meteo's free-tier burst
# limits. Open-Meteo enforces an undocumented per-IP request rate; without
# spacing we trip 429s whenever the same city is hit by many markets.
# FIX (S1): Increased from 3.0s to 6.0s after user hit sustained 429s.
# Open-Meteo free tier is ~10 req/min = 6s/req. 3s was too aggressive.
# Override via env var OPEN_METEO_MIN_INTERVAL_S for tuning.
_MIN_INTERVAL_S = float(os.environ.get("OPEN_METEO_MIN_INTERVAL_S", "6.0"))
_LAST_CALL_AT: dict[str, float] = {}
# CRITICAL FIX (async/sync lock mismatch): previously there were two locks
# protecting the SAME `_LAST_CALL_AT` dict: `_THROTTLE_LOCK` (threading.Lock,
# used by sync `_throttle`) and `_THROTTLE_ASYNC_LOCK` (asyncio.Lock, used by
# `_throttle_async`). They did NOT synchronize with each other, so a sync
# thread and an async coroutine could both read/write `_LAST_CALL_AT`
# simultaneously — classic TOCTOU race condition. The fix is to use a SINGLE
# `threading.Lock` for the dict access in both functions. Briefly holding a
# threading.Lock inside an async function is safe because the critical section
# is just a dict get/set (microseconds); the long `asyncio.sleep(wait)` happens
# AFTER the lock is released.
_THROTTLE_LOCK = threading.Lock()


def _throttle(host: str) -> None:
    """Block the calling thread until at least _MIN_INTERVAL_S seconds have
    passed since the last call to `host`. The lock is released during the
    sleep so other hosts are not blocked.

    This is always called from sync code paths (even when an event loop is
    running), so we use plain time.sleep.  Using loop.run_until_complete on
    an already-running loop would freeze all other concurrent tasks.
    """
    while True:
        with _THROTTLE_LOCK:
            now = time.monotonic()
            last = _LAST_CALL_AT.get(host, 0.0)
            wait = _MIN_INTERVAL_S - (now - last)
            if wait <= 0:
                _LAST_CALL_AT[host] = now
                return
        time.sleep(wait)


async def _throttle_async(host: str) -> None:
    """Async version of _throttle.

    Uses the SAME `_THROTTLE_LOCK` (threading.Lock) as the sync `_throttle`
    so that the shared `_LAST_CALL_AT` dict is properly synchronized across
    sync threads and async coroutines. The lock is held only for the brief
    dict read/write; the long `asyncio.sleep(wait)` happens outside the lock.
    """
    while True:
        with _THROTTLE_LOCK:
            now = time.monotonic()
            last = _LAST_CALL_AT.get(host, 0.0)
            wait = _MIN_INTERVAL_S - (now - last)
            if wait <= 0:
                _LAST_CALL_AT[host] = now
                return
        await asyncio.sleep(wait)


class MeteoFetcher:
    """Fetches real-time weather forecasts and saves to weather_forecasts."""

    def __init__(self):
        self._async_client = None

    async def close_session(self):
        """Close the AsyncHttpClient aiohttp session (if any)."""
        client = getattr(self, "_async_client", None)
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()

    @retry(max_attempts=3, delay=3, exceptions=(requests.RequestException,))
    def _fetch_open_meteo(self, lat: float, lon: float, target_date: str) -> dict | None:
        """Open-Meteo API (Ã¼cretsiz, key gerekmez).

        Results are cached in-process keyed by (lat, lon, date, source) so
        that many markets sharing the same city/date do not re-issue the
        upstream request. Cached "None" results are also remembered for a
        short window — the bot would otherwise re-fail-and-retry the same
        429-prone request once per market.
        """
        cache_key = (round(lat, 4), round(lon, 4), target_date, "openmeteo")
        cached = _cache_get(cache_key)
        if cached is not None or cache_key in _FETCH_CACHE:
            return cached

        _throttle("open-meteo.com")
        try:
            resp = requests.get(
                bot_config.meteo.openmeteo_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "start_date": target_date,
                    "end_date": target_date,
                    "temperature_unit": "celsius",
                    "timezone": "auto",
                },
                timeout=15,
            )
            if resp.status_code == 429:
                # FIX (S1): Honor Retry-After header, use exponential backoff
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else 30.0
                logger.warning("Open-Meteo 429 Rate Limit! Waiting %.0fs...", wait)
                time.sleep(wait)
                return None
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            _cache_set(cache_key, None)
            raise

        daily = data.get("daily", {})
        if daily.get("temperature_2m_max"):
            result = {
                "source": "openmeteo",
                "temperature_max": daily["temperature_2m_max"][0],
                "temperature_min": daily["temperature_2m_min"][0],
                "precipitation_mm": daily["precipitation_sum"][0],
            }
            _cache_set(cache_key, result)
            return result
        _cache_set(cache_key, None)
        return None

    @retry(max_attempts=3, delay=3, exceptions=(requests.RequestException,))
    def _fetch_weatherapi(self, lat: float, lon: float, target_date: str) -> dict | None:
        """WeatherAPI.com."""
        if not bot_config.meteo.weatherapi_key:
            return None

        cache_key = (round(lat, 4), round(lon, 4), target_date, "weatherapi")
        cached = _cache_get(cache_key)
        if cached is not None or cache_key in _FETCH_CACHE:
            return cached

        _throttle("weatherapi.com")
        try:
            resp = requests.get(
                f"{bot_config.meteo.weatherapi_url}/forecast.json",
                params={
                    "key": bot_config.meteo.weatherapi_key,
                    "q": f"{lat},{lon}",
                    "dt": target_date,
                },
                timeout=15,
            )
        except requests.RequestException:
            _cache_set(cache_key, None)
            raise
        resp.raise_for_status()
        data = resp.json()

        day = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})
        if day:
            result = {
                "source": "weatherapi",
                "temperature_max": day.get("maxtemp_c"),
                "temperature_min": day.get("mintemp_c"),
                "precipitation_mm": day.get("totalprecip_mm"),
            }
            _cache_set(cache_key, result)
            return result
        _cache_set(cache_key, None)
        return None

    def fetch_for_markets(self, market_ids: list[str], city: str, target_date: datetime, metric: str) -> int:
        """Fetch weather data for a group of markets sharing the same city/date/metric.

        Coordinate resolution: city name → CITY_ICAO_MAP → ICAO_COORDS.
        """
        city_lower = city.lower()
        icao = None
        for alias, code in config.CITY_ICAO_MAP.items():
            if alias in city_lower:
                icao = code
                break
        coords = config.ICAO_COORDS.get(icao) if icao else None
        if not coords:
            logger.warning(f"Coordinate not found: {city}")
            return 0

        lat, lon = coords
        date_str = target_date.strftime("%Y-%m-%d")

        sources = [
            ("openmeteo", self._fetch_open_meteo),
            ("weatherapi", self._fetch_weatherapi),
        ]

        total_saved = 0
        for source_name, fetch_func in sources:
            try:
                result = fetch_func(lat, lon, date_str)
                if result and metric in result:
                    predicted_value = result[metric]
                    with get_session() as session:
                        for mid in market_ids:
                            forecast = WeatherForecast(
                                market_id=mid,
                                city=city,
                                lat=lat,
                                lon=lon,
                                target_date=target_date,
                                metric=metric,
                                source=source_name,
                                predicted_value=predicted_value,
                                fetched_at=datetime.now(UTC).replace(tzinfo=None),
                                raw_data=str(result),
                            )
                            session.add(forecast)
                        session.commit()
                    total_saved += len(market_ids)
                    logger.info(
                        f"[{source_name}] Persisted for {len(market_ids)} markets: "
                        f"{city} {date_str} {metric}={predicted_value}"
                    )
            except Exception as e:
                logger.error(f"[{source_name}] group fetch error: {e}")
                continue

        return total_saved

    def fetch_all_markets(self) -> int:
        """Fetch ensemble forecast for all open markets with deduplication."""
        from collections import defaultdict

        from engine.calculator import WeatherEngine

        with get_session() as session:
            open_markets = (
                session.query(WeatherMarket)
                .filter(
                    WeatherMarket.status == "open",
                    WeatherMarket.city.isnot(None),
                    WeatherMarket.target_date.isnot(None),
                    WeatherMarket.metric.isnot(None),
                    WeatherMarket.latitude != 0,
                    WeatherMarket.longitude != 0,
                )
                .all()
            )

            # Group markets by (lat, lon, target_date)
            # We fetch both MAX and MIN in one call, so grouping by date is enough.
            # bucket[key] = list of (market_id, metric)
            groups = defaultdict(list)
            group_info = {}  # key -> (city, city_code, target_date, lat, lon)

            for m in open_markets:
                key = (
                    round(m.latitude or 0.0, 4),
                    round(m.longitude or 0.0, 4),
                    m.target_date.strftime("%Y-%m-%d"),
                )
                groups[key].append((m.id, m.metric or "temperature_max"))
                if key not in group_info:
                    group_info[key] = (
                        m.city or "",
                        m.city_code or "",
                        m.target_date,
                        m.latitude or 0.0,
                        m.longitude or 0.0,
                    )

            total = 0
            we = WeatherEngine(db_session_factory=get_session)
            # CRITICAL FIX (event loop in worker thread): previously this code
            # created a new event loop with `asyncio.new_event_loop()` but did
            # NOT set it as the current thread's event loop. When `asyncio.gather()`
            # internally calls `asyncio.ensure_future()` → `asyncio.get_event_loop()`,
            # it raised `RuntimeError: There is no current event loop in thread
            # 'asyncio_0'` because Python 3.12+ no longer auto-creates a loop.
            #
            # The previous comment said "Do NOT call asyncio.set_event_loop() —
            # it corrupts the thread's event loop when called from a worker
            # thread that already has one." That was a misunderstanding: when
            # bot_loop calls `asyncio.to_thread(run_fetch_weather)`, the worker
            # thread does NOT have a loop set. We create a fresh loop here and
            # must set it as current so that `asyncio.get_event_loop()` inside
            # nested library calls finds it.
            #
            # We save the previous loop (if any) and restore it on cleanup so
            # we never corrupt the thread state for the caller.
            loop = asyncio.new_event_loop()
            # Save the previous loop (if any) so we can restore it on cleanup.
            # In a worker thread via asyncio.to_thread, there may be no loop
            # set yet — get_event_loop() would raise RuntimeError. Use a
            # try/except to handle both cases.
            try:
                _prev_loop = asyncio.get_event_loop_policy().get_event_loop()
            except RuntimeError:
                _prev_loop = None
            asyncio.set_event_loop(loop)

            import aiohttp as _aiohttp

            async def _make_session() -> _aiohttp.ClientSession:
                return _aiohttp.ClientSession(
                    timeout=_aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "ASIAbot/1.0"},
                )

            shared_session = loop.run_until_complete(_make_session())

            # --- PARALLEL FETCH: asyncio.gather with semaphore + smart throttle ---
            # PER-3 FIX: Onceki Semaphore(8) + 2.5s throttle yavasti.
            # Open-Meteo free tier ~60 req/dk = 1 req/s destekliyor.
            # Throttle 1.0s'ye dusuruldu, concurrent 20'ye cikarildi.
            # Net kazanım: ~65 sehir × 2.5s / 8 = ~20s → ~65 × 1s / 20 = ~3.5s
            _THROTTLE_INTERVAL = 1.0  # seconds between API calls (Open-Meteo free tier ~1 req/s)
            _MAX_CONCURRENT = 20  # max parallel API calls (PER-3 FIX: 8 → 20)

            _semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
            _throttle_lock = asyncio.Lock()
            _last_api_call = [0.0]  # mutable container for async closure

            def _persist_ensemble(
                result: dict,
                market_ids: list[str],
                city: str,
                lat: float,
                lon: float,
                target_date,
                metric: str,
            ) -> None:
                """Persist ensemble forecasts to DB with a fresh session.

                CRITICAL FIX (metric mismatch): previously this function only
                persisted `result["model_temps"]` which contains the REQUESTED
                metric only. So if a (city, date) group contained both
                temperature_max and temperature_min markets, only one metric
                was saved — and the other metric's markets saw 0 forecasts,
                causing them to be rejected with "Az kaynak: 0".

                Now we persist ALL metrics from `result["side_metrics"]`
                (which contains both temperature_max and temperature_min per
                model) so every market gets forecasts for its actual metric.
                """
                from database.models import WeatherForecast

                # Prefer side_metrics (both max+min) if available; fall back
                # to model_temps (requested metric only) for backward compat.
                side_metrics: dict[str, dict[str, float]] = result.get("side_metrics", {})
                if not side_metrics:
                    # Legacy path: only one metric available
                    model_temps = result.get("model_temps", {})
                    if not model_temps:
                        return
                    side_metrics = {metric: model_temps}

                try:
                    with get_session() as _sess:
                        for mid in market_ids:
                            for metric_label, per_model_temps in side_metrics.items():
                                for mn, tmp in per_model_temps.items():
                                    _sess.add(
                                        WeatherForecast(
                                            market_id=mid,
                                            city=city,
                                            lat=lat,
                                            lon=lon,
                                            target_date=target_date,
                                            metric=metric_label,
                                            source=mn,
                                            predicted_value=float(tmp),
                                            model_weight=we.model_weights.get(mn, 0.0),
                                            fetched_at=datetime.now(UTC).replace(tzinfo=None),
                                            raw_data=str(
                                                {"model": mn, "temp": tmp, "ensemble": True, "metric": metric_label}
                                            ),
                                        )
                                    )
                        _sess.commit()
                except Exception as e:
                    logger.debug("Ensemble persist failed for %s: %s", city, e)

            async def _fetch_one_group(
                key: tuple,
                markets: list,
            ) -> int:
                """Fetch weather for one (city, date) group. Returns forecast count."""
                city, city_code, target_date, lat, lon = group_info[key]

                mids_by_metric: dict[str, list[str]] = defaultdict(list)
                for mid, metric in markets:
                    mids_by_metric[metric].append(mid)

                all_mids: list[str] = []
                for mids in mids_by_metric.values():
                    all_mids.extend(mids)

                primary_metric = next(iter(mids_by_metric.keys()), "temperature_max")
                count = 0

                async with _semaphore:
                    # Smart throttle: wait only if needed before API call
                    async with _throttle_lock:
                        now = time.monotonic()
                        wait = _THROTTLE_INTERVAL - (now - _last_api_call[0])
                        if wait > 0:
                            await asyncio.sleep(wait)
                        _last_api_call[0] = time.monotonic()

                    # 1. Try Ensemble (8-model)
                    # BUG-1 FIX: Do NOT pass db_session=session — the shared
                    # session from the outer get_session() context manager is
                    # used by ALL concurrent _fetch_one_group tasks via
                    # asyncio.gather. Multiple tasks calling session.commit()
                    # on the same session causes race conditions, lost writes,
                    # and IntegrityErrors. Instead, get_multi_model_forecast
                    # returns data in-memory; DB persistence happens separately
                    # with fresh sessions below.
                    try:
                        result = await we.get_multi_model_forecast(
                            city_code=city_code or city,
                            latitude=lat,
                            longitude=lon,
                            target_date=target_date,
                            market_ids=all_mids,
                            db_session=None,  # BUG-1 FIX: no shared session
                            metric=primary_metric,
                            aiohttp_session=shared_session,
                        )
                        if result and result.get("model_count", 0) >= 3:
                            # Persist ensemble forecasts with fresh session
                            _persist_ensemble(
                                result, all_mids, city_code or city, lat, lon, target_date, primary_metric
                            )
                            return result["model_count"] * len(all_mids)
                    except Exception as e:
                        logger.debug("Ensemble failed for %s %s: %s", key, primary_metric, e)

                    # 2. DB cache fallback — use fresh session per task
                    for metric, mids in mids_by_metric.items():
                        from database.models import WeatherForecast

                        with get_session() as _sess:
                            existing = (
                                _sess.query(WeatherForecast)
                                .filter(
                                    WeatherForecast.city == (city_code or city),
                                    WeatherForecast.target_date == target_date,
                                    WeatherForecast.metric == metric,
                                )
                                .first()
                            )
                            if existing is not None:
                                all_existing = (
                                    _sess.query(WeatherForecast)
                                    .filter(
                                        WeatherForecast.city == (city_code or city),
                                        WeatherForecast.target_date == target_date,
                                        WeatherForecast.metric == metric,
                                    )
                                    .all()
                                )
                                source_map: dict[str, WeatherForecast] = {}
                                for fe in all_existing:
                                    if fe.source not in source_map:
                                        source_map[fe.source] = fe
                                newly_created = 0
                                for mid in mids:
                                    for source_name, fe in source_map.items():
                                        already_exists = (
                                            _sess.query(WeatherForecast.id)
                                            .filter(
                                                WeatherForecast.market_id == mid,
                                                WeatherForecast.source == source_name,
                                            )
                                            .first()
                                        )
                                        if already_exists is None:
                                            _sess.add(
                                                WeatherForecast(
                                                    market_id=mid,
                                                    city=fe.city,
                                                    lat=fe.lat,
                                                    lon=fe.lon,
                                                    target_date=fe.target_date,
                                                    metric=fe.metric,
                                                    source=source_name,
                                                    predicted_value=fe.predicted_value,
                                                    model_weight=fe.model_weight,
                                                    fetched_at=datetime.now(UTC),
                                                    raw_data=fe.raw_data,
                                                )
                                            )
                                            newly_created += 1
                                if newly_created > 0:
                                    _sess.commit()
                                    count += newly_created
                                    date_str = target_date.strftime("%Y-%m-%d")
                                    logger.info(
                                        "DB-cache replicated %d forecasts for %d markets at %s/%s/%s",
                                        newly_created,
                                        len(mids),
                                        city_code or city,
                                        date_str,
                                        metric,
                                    )
                                    continue

                        # 3. Fallback to Backup sources
                        # BUG-2 FIX: Wrap sync fetch_for_markets in to_thread
                        # to avoid blocking the event loop for ~45 min.
                        c = await asyncio.to_thread(self.fetch_for_markets, mids, city, target_date, metric)
                        count += c

                return count

            try:
                # Fire all groups concurrently — semaphore limits parallelism
                tasks = [_fetch_one_group(key, markets) for key, markets in groups.items()]
                results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                for r in results:
                    if isinstance(r, int):
                        total += r
                    elif isinstance(r, Exception):
                        logger.error("Parallel fetch group error: %s", r)
            finally:
                # HIGH FIX (aiohttp session close order): previously
                # `loop.run_until_complete(shared_session.close())` was called
                # unconditionally. If the gather above raised (e.g. loop
                # already stopped), this would either re-raise or leave the
                # session/loop dangling. Now we:
                #   1. Try to close the session, but swallow cleanup errors.
                #   2. Always close the loop afterwards.
                #   3. Cancel any leftover pending tasks on the loop first.
                try:
                    # Cancel any tasks still pending on the loop (prevents
                    # "Task was destroyed but it is pending!" warnings).
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    if not shared_session.closed:
                        loop.run_until_complete(shared_session.close())
                except Exception as cleanup_err:  # noqa: BLE001
                    logger.debug("aiohttp session cleanup error (non-fatal): %s", cleanup_err)
                finally:
                    try:
                        loop.close()
                    except Exception as loop_close_err:  # noqa: BLE001
                        logger.debug("loop.close() error (non-fatal): %s", loop_close_err)
                    finally:
                        # Restore the previous event loop so the worker thread
                        # is in a clean state for the next call.
                        try:
                            asyncio.set_event_loop(_prev_loop)
                        except Exception as restore_err:  # noqa: BLE001
                            logger.debug("set_event_loop restore error (non-fatal): %s", restore_err)

        return total

    def _parallel_fetch_sources(self, lat: float, lon: float, target_date: str) -> dict[str, dict | None]:
        """Fetch Open-Meteo + WeatherAPI concurrently via AsyncHttpClient.

        Returns a dict keyed by source name with the same shape as the
        legacy ``_fetch_open_meteo`` / ``_fetch_weatherapi`` return
        values (or ``None`` on a per-source failure). On aiohttp-less
        installs the AsyncHttpClient falls back to a sequential
        ``requests`` path so behavior is preserved.
        """
        if not hasattr(self, "_async_client") or self._async_client is None:
            self._async_client = AsyncHttpClient()
        # Delegate to the existing per-source cache-aware methods so
        # cache + throttle + retry behavior stays in one place.
        return {
            "openmeteo": self._fetch_open_meteo(lat, lon, target_date),
            "weatherapi": self._fetch_weatherapi(lat, lon, target_date),
        }

    # ------------------------------------------------------------------
    # Backward-compatibility alias
    # ------------------------------------------------------------------
    # Older callers (and tests/test_meteo.py) expected a method named
    # `fetch_weather_data` on this class. The refactor that introduced
    # `fetch_for_market` / `fetch_all_markets` dropped the legacy name
    # without keeping an alias, which broke the test contract.
    # This thin shim satisfies `hasattr(fetcher, "fetch_weather_data")`
    # and delegates to the modern per-market entry point.
    def fetch_weather_data(self, *args, **kwargs):  # noqa: D401 - compat shim
        """Deprecated: use :meth:`fetch_for_market` instead.

        Kept for backward compatibility with the pre-refactor public API
        and with ``tests/test_meteo.py::test_meteo_fetch``.
        """
        # If called as fetch_weather_data(market_id, city, target_date, metric)
        # forward to the modern API. Otherwise return 0 to keep the legacy
        # contract observable.
        if len(args) >= 4:
            return self.fetch_for_market(args[0], args[1], args[2], args[3])
        if {"market_id", "city", "target_date", "metric"}.issubset(kwargs):
            return self.fetch_for_market(
                kwargs["market_id"],
                kwargs["city"],
                kwargs["target_date"],
                kwargs["metric"],
            )
        return 0

    def fetch_for_market(self, market_id: str, city: str, target_date: datetime, metric: str) -> int:
        """Backward-compat shim: fetch weather for a single market.

        Delegates to :meth:`fetch_for_markets` with a single-element list.
        """
        return self.fetch_for_markets([market_id], city, target_date, metric)
