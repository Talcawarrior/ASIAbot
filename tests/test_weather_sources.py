"""Unit tests for multi-source weather tracking (t_horizon) + Gamma proxy fix.

Covers:
- utils.weather_sources: VC key rotation, cache, 429 handling, IEM max, settlement_actual
- data_pipeline.t_horizon_collector: t0/t1/t2 upsert, city filtering, key pools
- data_pipeline.t_horizon_report: idempotent fill_actuals, kesişen report
- scrapers.polymarket: new-city auto-detection
- executor.settler: Gamma proxy retry/backoff
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest


# ── utils.weather_sources ──────────────────────────────────────────


class TestWeatherSources:
    def test_vc_key_rotation_returns_pool_keys(self):
        """VC key pool round-robin: next_vc_key cycles through 8 keys."""
        from utils.weather_sources import _vc_key

        with patch("config.settings.bot_config.meteo.vc_api_keys", ["k1", "k2", "k3"]):
            # Reset index by patching next_vc_key directly
            from config.settings import bot_config

            bot_config.meteo._vc_idx = 0  # type: ignore[attr-defined]
            keys = [_vc_key(), _vc_key(), _vc_key()]
            assert keys == ["k1", "k2", "k3"]

    def test_vc_daily_caches_result(self):
        """vc_daily caches per (lat, lon, date) for 1h TTL."""
        from utils import weather_sources as ws

        with patch.object(ws, "_vc_keys_available", return_value=True), patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"days": [{"tempmax": 30.5, "tempmin": 20.0, "source": "comb"}]}
            mock_get.return_value = mock_resp

            ws._VC_CACHE.clear()
            ws._VC_CACHE_TS.clear()
            d = date(2026, 8, 25)
            r1 = ws.vc_daily(41.0, 28.0, d)
            r2 = ws.vc_daily(41.0, 28.0, d)

            assert r1 is not None
            assert r1["tmax"] == 30.5
            assert r2["tmax"] == 30.5
            assert mock_get.call_count == 1  # cached

    def test_vc_daily_429_rotates_key(self):
        """On 429, vc_daily retries with rotated key."""
        from utils import weather_sources as ws

        with patch.object(ws, "_vc_keys_available", return_value=True), patch("requests.get") as mock_get:
            mock_429 = MagicMock()
            mock_429.status_code = 429
            mock_200 = MagicMock()
            mock_200.status_code = 200
            mock_200.json.return_value = {"days": [{"tempmax": 28.0, "tempmin": 18.0, "source": "comb"}]}
            mock_get.side_effect = [mock_429, mock_200]

            ws._VC_CACHE.clear()
            ws._VC_CACHE_TS.clear()
            d = date(2026, 8, 25)
            r = ws.vc_daily(41.0, 28.0, d)

            assert r is not None
            assert r["tmax"] == 28.0
            assert mock_get.call_count == 2

    def test_vc_daily_no_keys_returns_none(self):
        """vc_daily returns None when no VC keys configured."""
        from utils import weather_sources as ws

        with patch.object(ws, "_vc_keys_available", return_value=False):
            assert ws.vc_daily(41.0, 28.0, date(2026, 8, 25)) is None

    def test_iem_daily_max_parses_tmpf_to_celsius(self):
        """IEM asos.py CSV -> max(tmpf) converted to Celsius."""
        from utils import weather_sources as ws

        fake_csv = "station,valid,tmpf\nLGA,2026-08-25 12:00,82\nLGA,2026-08-25 13:00,86\nLGA,2026-08-25 14:00,M\n"
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = fake_csv
            mock_get.return_value = mock_resp

            result = ws.iem_daily_max("LGA", date(2026, 8, 25))
            # max tmpf=86 -> (86-32)*5/9 = 30.0
            assert result == pytest.approx(30.0, abs=0.1)

    def test_iem_daily_max_empty_returns_none(self):
        """IEM returns None when no valid observations."""
        from utils import weather_sources as ws

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "station,valid,tmpf\nLGA,2026-08-25 12:00,M\n"
            mock_get.return_value = mock_resp

            assert ws.iem_daily_max("LGA", date(2026, 8, 25)) is None

    def test_settlement_actual_uses_iem_for_us(self):
        """US (K***) uses IEM first, VC fallback."""
        from utils import weather_sources as ws

        with patch.object(ws, "iem_daily_max", return_value=27.5) as mock_iem:
            actual, src = ws.settlement_actual("KLGA", 40.77, -73.87, date(2026, 8, 25))
            assert actual == 27.5
            assert src == "IEM"
            mock_iem.assert_called_once()

    def test_settlement_actual_vc_fallback_for_non_us(self):
        """Non-US airports fall back to VC."""
        from utils import weather_sources as ws

        with (
            patch.object(ws, "iem_daily_max", return_value=None),
            patch.object(ws, "vc_daily", return_value={"tmax": 28.3, "tmin": 20.0, "source": "comb"}),
        ):
            actual, src = ws.settlement_actual("LFPG", 49.0, 2.55, date(2026, 8, 25))
            assert actual == 28.3
            assert src == "VC"


# ── data_pipeline.t_horizon_collector ─────────────────────────────


class TestTHorizonCollector:
    def test_vc_range_rotates_keys_on_429(self):
        """_vc_range tries all keys on 429, returns data on 200."""
        from data_pipeline import t_horizon_collector as tc

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "days": [
                {"datetime": "2026-08-25", "tempmax": 30.0, "tempmin": 20.0},
                {"datetime": "2026-08-26", "tempmax": 31.0, "tempmin": 21.0},
            ]
        }
        tc._BAD_VC_KEYS.clear()
        with (
            patch.object(tc.bot_config.meteo, "vc_api_keys", ["k1", "k2"]),
            patch("requests.get", side_effect=[mock_429, mock_200]) as mock_get,
        ):
            result = tc._vc_range(41.0, 28.0, date(2026, 8, 25), date(2026, 8, 26))
            assert "2026-08-25" in result
            assert result["2026-08-25"]["tmax"] == 30.0
            assert mock_get.call_count == 2
            assert "k1" in tc._BAD_VC_KEYS  # 429 yiyen key karalistede

    def test_vc_range_skips_blacklisted_keys(self):
        """After a key is blacklisted, _vc_range does not retry it."""
        from data_pipeline import t_horizon_collector as tc

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"days": [{"datetime": "2026-08-25", "tempmax": 30.0, "tempmin": 20.0}]}
        tc._BAD_VC_KEYS.clear()
        tc._BAD_VC_KEYS.add("k1")
        with (
            patch.object(tc.bot_config.meteo, "vc_api_keys", ["k1", "k2"]),
            patch("requests.get", return_value=mock_200) as mock_get,
        ):
            result = tc._vc_range(41.0, 28.0, date(2026, 8, 25), date(2026, 8, 26))
            assert "2026-08-25" in result
            # k1 hic denenmemis (sadece k2)
            mock_get.assert_called_once()
            assert mock_get.call_args.kwargs["params"]["key"] == "k2"
        tc._BAD_VC_KEYS.clear()

    def test_vc_range_no_keys_returns_empty(self):
        from data_pipeline import t_horizon_collector as tc

        with patch.object(tc.bot_config.meteo, "vc_api_keys", []), patch.object(tc, "VC_KEY", ""):
            assert tc._vc_range(41.0, 28.0, date(2026, 8, 25), date(2026, 8, 26)) == {}

    def test_openweather_range_aggregates_max(self):
        """OpenWeather /3h slots -> daily max/min aggregation."""
        from data_pipeline import t_horizon_collector as tc

        from datetime import timezone as tz

        ts = int(datetime(2026, 8, 25, 6, 0, tzinfo=tz.utc).timestamp())
        ts2 = int(datetime(2026, 8, 25, 12, 0, tzinfo=tz.utc).timestamp())
        payload = {
            "list": [
                {"dt": ts, "main": {"temp_max": 28.0, "temp_min": 18.0}},
                {"dt": ts2, "main": {"temp_max": 30.0, "temp_min": 19.0}},
            ]
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = payload
            mock_get.return_value = mock_resp

            result = tc._openweather_range(41.0, 28.0)
            assert result["2026-08-25"]["tmax"] == 30.0
            assert result["2026-08-25"]["tmin"] == 18.0

    def test_weatherapi_range_rotates_on_429(self):
        from data_pipeline import t_horizon_collector as tc

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "forecast": {"forecastday": [{"date": "2026-08-25", "day": {"maxtemp_c": 29.0, "mintemp_c": 19.0}}]}
        }
        with (
            patch.object(tc.bot_config.meteo, "weatherapi_keys", ["k1", "k2"]),
            patch("requests.get", side_effect=[mock_429, mock_200]) as mock_get,
        ):
            result = tc._weatherapi_range(41.0, 28.0)
            assert result["2026-08-25"]["tmax"] == 29.0
            assert mock_get.call_count == 2


# ── data_pipeline.t_horizon_report ────────────────────────────────


class TestTHorizonReport:
    def test_fill_actuals_is_idempotent(self):
        """fill_actuals only fills NULL actual_max rows (no overwrite)."""
        from data_pipeline import t_horizon_report as tr
        from database.db import get_session
        from database.models import ForecastArchive

        tgt = date(2026, 8, 25)
        s1_id = s2_id = None
        with get_session() as session:
            session.query(ForecastArchive).filter(
                ForecastArchive.target_date == datetime.combine(tgt, datetime.min.time())
            ).delete()
            session.commit()

            # seed two rows: one already filled, one NULL
            s1 = ForecastArchive(
                city_code="LFPG",
                target_date=datetime.combine(tgt, datetime.min.time()),
                horizon=0,
                source="visual_crossing",
                predicted_max=28.0,
                actual_max=28.0,
                actual_source="VC",
                is_match=True,
            )
            s2 = ForecastArchive(
                city_code="LFPG",
                target_date=datetime.combine(tgt, datetime.min.time()),
                horizon=1,
                source="visual_crossing",
                predicted_max=29.0,
            )
            session.add_all([s1, s2])
            session.flush()
            s1_id = s1.id
            s2_id = s2.id
            session.commit()

        # settlement_actual returns different value; filled row must NOT change
        with (
            patch.object(tr, "settlement_actual", return_value=(30.0, "VC")),
            patch("utils.weather_sources.vc_daily", return_value={"tmin": 20.0}),
        ):
            tr.fill_actuals_for_date(tgt)

        with get_session() as session:
            r1 = session.query(ForecastArchive).filter(ForecastArchive.id == s1_id).first()
            r2 = session.query(ForecastArchive).filter(ForecastArchive.id == s2_id).first()
            # idempotent: already-filled row keeps 28.0, NULL row gets 30.0
            assert r1.actual_max == 28.0
            assert r2.actual_max == 30.0
            assert r2.is_match is False  # |29-30| = 1.0 > 0.5
            session.query(ForecastArchive).filter(ForecastArchive.id.in_([s1_id, s2_id])).delete()
            session.commit()

    def test_generate_report_includes_sources(self):
        """generate_report builds a text report with source-level hit rate."""
        from data_pipeline import t_horizon_report as tr

        with patch.object(tr, "get_session", side_effect=RuntimeError("should not hit DB")):
            pass
        # generate_report needs DB rows; run with empty DB -> valid empty report
        report = tr.generate_report(days=3)
        assert "Kaynak Bazli" in report
        assert "visual_crossing" in report


# ── scrapers.polymarket new-city detection ────────────────────────


class TestNewCityDetection:
    def test_extract_city_known(self):
        from scrapers.polymarket import PolymarketScraper

        s = PolymarketScraper()
        assert s._extract_city("Will the highest temperature in New York be 30C on August 27?") == "KLGA"

    def test_extract_city_new(self):
        from scrapers.polymarket import PolymarketScraper

        s = PolymarketScraper()
        assert s._extract_city("Will the highest temperature in Kigali be 30C on August 27?") == "NEW_Kigali"

    def test_extract_city_new_reykjavik(self):
        from scrapers.polymarket import PolymarketScraper

        s = PolymarketScraper()
        assert s._extract_city("What will the low temperature be in Reykjavik on August 28?") == "NEW_Reykjavik"

    def test_extract_city_stopword_filtered(self):
        """'be' / 'on' / 'the' should not be treated as cities."""
        from scrapers.polymarket import PolymarketScraper

        s = PolymarketScraper()
        assert s._extract_city("Will the highest temperature in Kigali be 30C on August 27?") == "NEW_Kigali"

    def test_is_weather_market_new_city(self):
        from scrapers.polymarket import PolymarketScraper

        s = PolymarketScraper()
        m = {
            "question": "Will the highest temperature in Kigali be 30C on August 27?",
            "description": "Weather temperature market",
            "title": "Kigali temperature",
        }
        assert s._is_weather_market(m) is True


# ── executor.settler Gamma proxy ──────────────────────────────────


class TestSettlerGamma:
    def test_call_gamma_api_proxy_retry(self):
        """_call_gamma_api retries with backoff on 429 then succeeds."""
        from executor.settler import SettlementEngine, requests

        eng = SettlementEngine()
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"id": "1", "closed": True}
        with patch.object(requests, "get", side_effect=[mock_429, mock_200]) as mock_get, patch("time.sleep"):
            market = MagicMock()
            market.id = "1"
            result = eng._call_gamma_api(market)
            assert result == {"id": "1", "closed": True}
            assert mock_get.call_count == 2

    def test_call_gamma_api_all_fail_returns_none(self):
        from executor.settler import SettlementEngine, requests

        eng = SettlementEngine()
        with (
            patch.object(requests, "get", side_effect=requests.ConnectionError("conn reset")) as mock_get,
            patch("time.sleep"),
        ):
            market = MagicMock()
            market.id = "2"
            result = eng._call_gamma_api(market)
            assert result is None
            assert mock_get.call_count == 3
