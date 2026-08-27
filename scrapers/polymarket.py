"""Polymarket scraper module fetching and filtering weather events."""

import json
import logging
import re
from datetime import UTC, datetime

import requests

from config.settings import bot_config, config
from database.db import get_session
from database.models import WeatherMarket
from engine.market_parser import MarketParser
from scrapers.async_client import AsyncHttpClient

from utils.retry import retry

logger = logging.getLogger("SCRAPER_POLYMARKET")


class PolymarketScraper:
    """Scrapes weather prediction markets from Polymarket Gamma API."""

    def __init__(self):
        self.gamma_url = bot_config.polymarket.gamma_url
        self.keywords = bot_config.polymarket.weather_keywords
        self._async_client = None

    async def init_session(self):
        """Mock init session for test compatibility."""
        pass

    async def close_session(self):
        """Close the AsyncHttpClient aiohttp session (if any)."""
        client = getattr(self, "_async_client", None)
        if client is not None:
            await client.aclose()

    @retry(max_attempts=3, delay=5, exceptions=(requests.RequestException,))
    def _fetch_raw_markets(self) -> list[dict]:
        """Polymarket'ten ham veri çek — public-search + today+2 gün + parallel.

        Tier 3 #12: parallel path now goes through AsyncHttpClient which
        uses aiohttp + bounded concurrency (8) + 250 ms per-host throttle
        and an in-process cache. The sync ThreadPoolExecutor path is
        kept as the no-aiohttp fallback (the AsyncHttpClient handles
        that automatically via ``_HAS_AIOHTTP``).
        """
        from datetime import timedelta
        from urllib.parse import urlparse

        today = datetime.now(UTC).replace(tzinfo=None)
        # Generate date strings in multiple formats to match Polymarket titles
        # which use "June 7" (no zero-pad), "June 07" (zero-pad), or "Jun 7".
        import calendar

        date_strs = []
        for i in range(3):
            d = today + timedelta(days=i)
            month_name = calendar.month_name[d.month]  # "June"
            month_abbr = calendar.month_abbr[d.month]  # "Jun"
            day_no_pad = str(d.day)  # "7"
            day_zero_pad = f"{d.day:02d}"  # "07"
            date_strs.extend(
                [
                    f"{month_name} {day_no_pad}",  # "June 7"
                    f"{month_name} {day_zero_pad}",  # "June 07"
                    f"{month_abbr} {day_no_pad}",  # "Jun 7"
                    f"{month_abbr} {day_zero_pad}",  # "Jun 07"
                ]
            )

        queries = [
            "highest temperature",
            "lowest temperature",
            "temperature",
            "weather temperature",
        ]
        # Also add 5 city-specific queries to broaden coverage beyond
        # the public-search top results.
        queries += [
            # Top US markets (highest volume on Polymarket)
            "dallas temperature",
            "miami temperature",
            "new york temperature",
            "chicago temperature",
            "houston temperature",
            "los angeles temperature",
            "phoenix temperature",
            # International (frequent on Polymarket)
            "london temperature",
            "paris temperature",
            "tokyo temperature",
            "seoul temperature",
            "istanbul temperature",
        ]

        gamma_host = urlparse(self.gamma_url).netloc
        # Build the batched (url, params, host) tuples once. AsyncHttpClient
        # takes care of bounded concurrency, per-host throttle and cache.
        items = [
            (
                f"{self.gamma_url}/public-search",
                {"q": q, "limit_per_type": 50},
                gamma_host,
            )
            for q in queries
        ]
        if not hasattr(self, "_async_client") or self._async_client is None:
            self._async_client = AsyncHttpClient()
        results = self._async_client.fetch_many(items)
        # Each entry is the parsed JSON or None on failure; events live
        # under the "events" key. Skip failures.
        per_query_events: list[list[dict]] = []
        for r in results:
            if not r:
                per_query_events.append([])
                continue
            per_query_events.append(r.get("events", []) or [])

        all_events: list[dict] = []
        seen_slugs: set[str] = set()
        for events in per_query_events:
            for e in events:
                slug = e.get("slug", "")
                title = e.get("title", "")
                if slug in seen_slugs:
                    continue
                # Keep only today + next 2 days
                if not any(d in title for d in date_strs):
                    continue
                seen_slugs.add(slug)
                # Flatten event's markets so the rest of the pipeline
                # (which expects raw market dicts) keeps working.
                for m in e.get("markets", []):
                    m.setdefault("title", title)
                    m.setdefault("description", title)
                    m.setdefault("event_slug", slug)
                    all_events.append(m)

        logger.info(f"Toplam {len(all_events)} market çekildi ({len(seen_slugs)} event, {len(queries)} sorgu)")
        return all_events

    async def fetch_polymarket_events(self, limit: int = 100) -> list[dict]:
        """Fetch daily-temperature events for compatibility with test suite."""
        raw_markets = self._fetch_raw_markets()
        formatted = []
        for raw in raw_markets[:limit]:
            formatted.append(self._parse_market(raw))
        return formatted

    def _is_weather_market(self, market: dict) -> bool:
        """Weather market check: BOTH a known city AND a strong weather term required.

        Only temperature markets are accepted. Precipitation, wind, storm,
        and humidity markets are explicitly rejected.
        """
        question = (
            market.get("question", "") + " " + market.get("description", "") + " " + market.get("title", "")
        ).lower()
        # 1) Must mention a known city (any key from CITY_ICAO_MAP) OR a
        #    regex-detectable city pattern (so new cities get auto-captured)
        city_match = any(city_key in question for city_key in config.CITY_ICAO_MAP.keys())
        if not city_match:
            # Auto-detect unknown-city patterns like "temperature in Kigali on..."
            for pattern in self._CITY_DETECT_PATTERNS:
                if re.search(pattern, question, re.IGNORECASE):
                    city_match = True
                    break
        if not city_match:
            return False
        # 2) Must contain a strong weather term (reject sports/politics that
        #    happen to share a city name like "Boston Bruins" or "Dallas Cowboys")
        strong_terms = (
            "temperature",
            "highest",
            "lowest",
            "heat",
            "cold",
            "°F",
            "°C",
            "celsius",
            "fahrenheit",
            "weather",
        )
        if not any(term in question for term in strong_terms):
            return False
        # 3) Explicitly reject non-temperature weather markets (rain, snow, storm, etc.)
        reject_terms = (
            "rain",
            "snow",
            "storm",
            "hurricane",
            "tornado",
            "precipitation",
            "humidity",
            "wind",
            "snowfall",
            "rainfall",
        )
        if any(term in question for term in reject_terms):
            return False
        return True

    def _parse_market(self, raw: dict) -> dict:
        """Ham marketi yapılandırılmış veriye çevir."""
        # 1) YES/NO price — outcomePrices is PRIMARY (always sums to 1.0).
        #    tokens[] and lastTradePrice are fallbacks only.
        yes_price = None
        no_price = None

        # PRIMARY: outcomePrices (Gamma API — always [YES, NO] summing to 1.0)
        op = raw.get("outcomePrices", "")
        if op:
            try:
                parsed_op = json.loads(op) if isinstance(op, str) else op
                if isinstance(parsed_op, list) and len(parsed_op) >= 2:
                    yp = float(parsed_op[0]) if parsed_op[0] else None
                    np_ = float(parsed_op[1]) if parsed_op[1] else None
                    if yp is not None and np_ is not None:
                        yes_price = yp
                        no_price = np_
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # FALLBACK: tokens[] (skip price=0 or price=1 — means no orderbook)
        if yes_price is None or no_price is None:
            for token in raw.get("tokens", []) or []:
                outcome = (token.get("outcome", "") or "").upper()
                try:
                    p = float(token.get("price", 0) or 0)
                except (TypeError, ValueError):
                    p = None
                if p is not None and 0 < p < 1:
                    if outcome == "YES" and yes_price is None:
                        yes_price = p
                    elif outcome == "NO" and no_price is None:
                        no_price = p

        # FALLBACK: public-search fields
        if yes_price is None:
            for key in ("lastTradePrice", "bestBid", "yes_price", "yesPrice"):
                v = raw.get(key)
                if v is not None:
                    try:
                        p = float(v)
                        if 0 < p < 1:
                            yes_price = p
                            break
                    except (TypeError, ValueError):
                        pass
        if no_price is None:
            for key in ("noPrice", "no_price", "bestAsk"):
                v = raw.get(key)
                if v is not None:
                    try:
                        p = float(v)
                        if 0 < p < 1:
                            no_price = p
                            break
                    except (TypeError, ValueError):
                        pass

        # DERIVE missing side
        if no_price is None and yes_price is not None:
            no_price = max(0.0, min(1.0, round(1.0 - yes_price, 4)))
        if yes_price is None and no_price is not None:
            yes_price = max(0.0, min(1.0, round(1.0 - no_price, 4)))

        # VALIDATE: YES + NO must sum to ~1.0. If not, trust outcomePrices.
        if yes_price is not None and no_price is not None:
            total = yes_price + no_price
            if abs(total - 1.0) > 0.05:
                # Prices don't sum to 1.0 — recalculate from outcomePrices or derive
                op2 = raw.get("outcomePrices", "")
                if op2:
                    try:
                        parsed_op2 = json.loads(op2) if isinstance(op2, str) else op2
                        if isinstance(parsed_op2, list) and len(parsed_op2) >= 2:
                            yes_price = float(parsed_op2[0])
                            no_price = float(parsed_op2[1])
                    except Exception:
                        pass
                # If still bad, derive NO from YES
                if yes_price is not None and no_price is not None:
                    total2 = yes_price + no_price
                    if abs(total2 - 1.0) > 0.05:
                        no_price = round(1.0 - yes_price, 4)

        if yes_price is None:
            yes_price = 0.5
        if no_price is None:
            no_price = 0.5

        # Extract city name dynamically from ICAO map keys
        city_name = "Unknown"
        title = raw.get("title", "") or raw.get("question", "")
        question = raw.get("question", "") or raw.get("description", "") or raw.get("title", "")
        title_lower = (title or "").lower()
        question_lower = (question or "").lower()
        for k in config.CITY_ICAO_MAP.keys():
            if k in title_lower or k in question_lower:
                city_name = k.title()
                break

        if city_name == "Unknown":
            event_title = title or ""
            city_name = (
                event_title.split(" - ")[0].strip()
                if event_title and " - " in event_title
                else (event_title.split()[0] if event_title else "Unknown")
            )

        # Parse structured market metadata
        target_date = self._extract_date(title)
        parser = MarketParser()
        threshold_result = parser._extract_threshold(question)
        threshold, threshold_unit, threshold_low, threshold_high = (
            threshold_result if threshold_result else (0.0, "celsius", None, None)
        )
        metric = "temperature_max" if "highest" in question_lower or "above" in question_lower else "temperature_min"
        city_code = self._extract_city(question)
        market_type = self._determine_market_type(question)
        coords = self.get_city_coords(city_code) if city_code else None

        # Ensure correct numeric market ID matching the betting and settlement engines
        market_id_val = str(raw.get("id"))

        return {
            "id": market_id_val,
            "condition_id": raw.get("condition_id"),
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": float(raw.get("volume", 0) or 0),
            "liquidity": float(raw.get("liquidity", 0) or 0),
            "end_date": raw.get("end_date_iso") or raw.get("endDate"),
            "raw_data": json.dumps(raw),
            "city_name": city_name,
            "city": city_name,
            "target_date": target_date,
            "threshold": threshold,
            "threshold_unit": threshold_unit,
            "threshold_low": threshold_low,
            "threshold_high": threshold_high,
            "metric": metric,
            "city_code": city_code,
            "market_type": market_type,
            "latitude": coords[0] if coords else 0.0,
            "longitude": coords[1] if coords else 0.0,
        }

    def fetch_and_save(self) -> int:
        """Ana fonksiyon: Çek -> Filtrele -> Kaydet."""
        try:
            raw_markets = self._fetch_raw_markets()
        except Exception as e:
            logger.warning(
                "Polymarket API hatasi (Gamma blocked/timeout): %s - 0 market, bot devam ediyor",
                e,
            )
            return 0

        weather_markets = [m for m in raw_markets if self._is_weather_market(m)]
        logger.info(f"{len(weather_markets)} hava durumu marketi bulundu")

        # Auto-detect NEW_ cities and record them to a file for the operator
        new_cities: dict[str, int] = {}
        for raw in weather_markets:
            q = (raw.get("question", "") + " " + raw.get("description", "") + " " + raw.get("title", "")).lower()
            for pattern in self._CITY_DETECT_PATTERNS:
                m = re.search(pattern, q, re.IGNORECASE)
                if m:
                    cn = m.group(1).strip().title()
                    if len(cn) > 2 and cn.lower() not in self._CITY_STOPWORDS:
                        new_cities[cn] = new_cities.get(cn, 0) + 1
        if new_cities:
            self._record_new_cities(new_cities)

        saved = 0
        with get_session() as session:
            for raw in weather_markets:
                try:
                    parsed = self._parse_market(raw)

                    # VALIDATE: YES + NO must sum to 1.0 — fix if not
                    yp = parsed.get("yes_price", 0)
                    np_ = parsed.get("no_price", 0)
                    if yp is not None and np_ is not None:
                        total = yp + np_
                        if abs(total - 1.0) > 0.05:
                            logger.warning(
                                "Price sum=%.2f != 1.0 for market %s (YES=%.4f NO=%.4f) — deriving NO from YES",
                                total,
                                parsed["id"],
                                yp,
                                np_,
                            )
                            parsed["no_price"] = round(1.0 - yp, 4)

                    # Markets without ICAO coordinates → no_coords status
                    has_coords = parsed["latitude"] != 0.0 or parsed["longitude"] != 0.0
                    if not has_coords and parsed["city_code"]:
                        logger.warning(
                            "No coordinates for city=%s (ICAO=%s) market=%s question=%r — status=no_coords",
                            parsed.get("city_name", "?"),
                            parsed["city_code"],
                            parsed["id"],
                            (parsed.get("question") or "")[:80],
                        )

                    # Upsert
                    existing = session.query(WeatherMarket).filter_by(id=parsed["id"]).first()

                    # Skip markets with missing target_date or zero threshold
                    if parsed["target_date"] is None:
                        logger.warning(f"Skipping market {parsed['id']}: no target_date parsed")
                        continue
                    threshold_c = parsed["threshold"]
                    if threshold_c == 0.0:
                        logger.warning(f"Skipping market {parsed['id']}: threshold is 0.0")
                        continue
                    # Sanity guard: Celsius değer -40..55 aralığında değilse atla
                    if threshold_c < -40 or threshold_c > 55:
                        logger.warning(
                            "Skipping market %s: threshold %.1f°C outside sane range [-40, 55] — question=%r",
                            parsed["id"],
                            threshold_c,
                            (parsed.get("question") or "")[:80],
                        )
                        continue

                    status = "no_coords" if not has_coords else "open"

                    if existing:
                        existing.yes_price = parsed["yes_price"]
                        existing.no_price = parsed["no_price"]
                        existing.volume = parsed["volume"]
                        existing.liquidity = parsed["liquidity"]
                        existing.city = parsed["city"]
                        existing.last_updated = datetime.now(UTC).replace(tzinfo=None)
                        existing.raw_data = parsed["raw_data"]
                        existing.target_date = parsed["target_date"]
                        existing.threshold = parsed["threshold"]
                        existing.metric = parsed["metric"]
                        existing.city_code = parsed["city_code"]
                        existing.latitude = parsed["latitude"]
                        existing.longitude = parsed["longitude"]
                        existing.status = status
                        existing.threshold_low = parsed.get("threshold_low")
                        existing.threshold_high = parsed.get("threshold_high")
                    else:
                        market = WeatherMarket(
                            id=parsed["id"],
                            question=parsed["question"],
                            yes_price=parsed["yes_price"],
                            no_price=parsed["no_price"],
                            volume=parsed["volume"],
                            liquidity=parsed["liquidity"],
                            city=parsed["city"],
                            first_seen=datetime.now(UTC).replace(tzinfo=None),
                            last_updated=datetime.now(UTC).replace(tzinfo=None),
                            raw_data=parsed["raw_data"],
                            status=status,
                            target_date=parsed["target_date"],
                            threshold=parsed["threshold"],
                            threshold_low=parsed.get("threshold_low"),
                            threshold_high=parsed.get("threshold_high"),
                            metric=parsed["metric"],
                            city_code=parsed["city_code"],
                            market_type=parsed["market_type"],
                            latitude=parsed["latitude"],
                            longitude=parsed["longitude"],
                        )
                        session.add(market)
                    saved += 1

                except Exception as e:
                    logger.error(f"Market parse hatası {raw.get('id')}: {e}")
                    continue

            logger.info(f"{saved} market kaydedildi/güncellendi")
        return saved

    @staticmethod
    def get_city_coords(city_code: str) -> tuple | None:
        """ICAO kodundan koordinat bul — merkezi Config.ICAO_COORDS."""
        return config.ICAO_COORDS.get(city_code)

    def _extract_date(self, title: str) -> datetime | None:
        """Parse a date from a market title string.

        Tries three patterns in order:
          1. "June 9 2026" or "June 9th, 2026"
          2. "2026-06-09" (ISO)
          3. "June 9"       (yearless — uses current year)

        Returns a datetime at 23:59:59 on the parsed day, or None.
        """
        if not title:
            return None
        # Pattern 1: "June 9 2026" or "June 9th, 2026" or "Jun 9 2026"
        match = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})", title)
        if match:
            month_str, day, year = (
                match.group(1),
                int(match.group(2)),
                int(match.group(3)),
            )
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    dt = datetime.strptime(f"{month_str} {day} {year}", fmt)
                    return dt.replace(hour=23, minute=59, second=59)
                except ValueError:
                    continue
        # Pattern 2: ISO "2026-06-09"
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", title)
        if match:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            return datetime(year, month, day, 23, 59, 59)
        # Pattern 3: "June 9" (yearless) — only valid month names to avoid
        # false matches like "above 90" or "will 100"
        _MONTH_NAMES = (  # noqa: N806
            "January|February|March|April|May|June|July|"
            "August|September|October|November|December|"
            "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
        )
        match = re.search(rf"(?:{_MONTH_NAMES})\s+(\d{{1,2}})", title, re.IGNORECASE)
        if match:
            month_str, day = match.group(0).split()[0], int(match.group(1))
            today = datetime.now()
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    dt = datetime.strptime(f"{month_str} {day} {today.year}", fmt)
                    return dt.replace(hour=23, minute=59, second=59)
                except ValueError:
                    continue
        return None

    # Regex patterns for auto-detecting cities not in config
    # Matches patterns like "in Chicago on", "Chicago on", "Chicago, IL", "temperature in London"
    _CITY_DETECT_PATTERNS = [
        r"\bin\s+([A-Z][a-z]+)\s+on\s",  # "in Chicago on"
        r"\bin\s+([A-Z][a-z]+)\s+(?:on|at|for)\s",  # "in Chicago at"
        r"\b([A-Z][a-z]+)\s+on\s+\w+\s+\d{1,2}",  # "Chicago on August 27"
        r"\b([A-Z][a-z]+)\s+\d{1,2}(?:st|nd|rd|th)?\s+(?:°|deg)",  # "Chicago 27°"
        r"temperature\s+in\s+([A-Z][a-z]+)",  # "temperature in London"
        r"\b([A-Z][a-z]+)\s*,\s*[A-Z]{2}\b",  # "Chicago, IL" or "Paris, FR"
    ]

    _CITY_STOPWORDS = {
        "on",
        "at",
        "for",
        "in",
        "the",
        "of",
        "be",
        "will",
        "what",
        "how",
        "many",
        "which",
        "highest",
        "lowest",
        "average",
        "temperature",
        "weather",
        "station",
        "stations",
        "day",
        "days",
        "degree",
        "degrees",
        "fahrenheit",
        "celsius",
        "heat",
        "cold",
        "record",
        "records",
        "broken",
        "all-time",
        "august",
        "july",
        "september",
        "june",
        "may",
    }

    def _extract_city(self, text: str) -> str:
        if not text:
            return ""
        text_lower = text.lower()
        # 1) Config'deki bilinen şehirler (hızlı yol)
        for city_name, icao_code in config.CITY_ICAO_MAP.items():
            if city_name in text_lower:
                return icao_code
        # 2) Config dışı şehirleri regex ile tespit et (yeni şehirler otomatik yakala)
        for pattern in self._CITY_DETECT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                city_name = match.group(1).strip().title()
                if len(city_name) > 2 and city_name.lower() not in self._CITY_STOPWORDS:
                    # Yeni şehir tespit edildi - "NEW_" prefix ile kaydet, config'e eklenecek
                    logger.info(
                        "Auto-detected new city: %s from pattern '%s' in text: %s...", city_name, pattern, text[:100]
                    )
                    return f"NEW_{city_name}"
        return ""

    def _record_new_cities(self, cities: dict[str, int]) -> None:
        """Persist auto-detected cities to data/detected_new_cities.json."""
        try:
            from config.settings import BASE_DIR
            import os

            path = os.path.join(BASE_DIR, "data", "detected_new_cities.json")
            existing = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    existing = {}
            for cn, cnt in cities.items():
                existing[cn] = existing.get(cn, 0) + cnt
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            logger.info("New cities recorded to %s: %s", path, sorted(cities.keys()))
        except Exception as e:
            logger.warning("Could not record new cities: %s", e)

    def _extract_strike(self, question: str) -> float:
        if not question:
            return 0.0
        patterns = [
            r"(\d+)\s*\°\s*C",
            r"(\d+)\s*\°\s*F",
            r"(\d+)\s*degrees?\s*[CF]?",
            r"above\s+(\d+)",
            r"below\s+(\d+)",
            r"be\s+(\d+)\s*\°?",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                try:
                    strike = float(match.group(1))
                    if "F" in question.upper() or "FAHRENHEIT" in question.upper():
                        strike = (strike - 32) * 5 / 9
                    return round(strike, 1)
                except ValueError:
                    continue
        return 0.0

    def _determine_market_type(self, question: str) -> str:
        question_lower = question.lower()
        if "above" in question_lower or "higher" in question_lower or "over" in question_lower:
            return "HIGH"
        if "below" in question_lower or "lower" in question_lower or "under" in question_lower:
            return "LOW"
        if "or below" in question_lower or "or higher" in question_lower:
            if "or below" in question_lower:
                return "LOW"
            if "or higher" in question_lower:
                return "HIGH"
        return "RANGE"
