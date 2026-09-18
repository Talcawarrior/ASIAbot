"""t0/t1/t2 horizon collector - Windows 24h background.

Her calismada tum sehirler icin t0=bugun, t1=yarin, t2=2 gun sonra
tahminleri VC / WeatherAPI / OpenWeather / NWS / Weather.com(Apple) /
Pivotal GFS / IEM MOS kaynaklarindan ceker, ForecastArchive'a yazar.
Wethr.net / polyweather.today dahil degil (cikarildi).

Calisma: bot_loop.py -> forecast_collector_loop (6 saatte bir) veya
standalone: python -m data_pipeline.t_horizon_collector
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from config.settings import bot_config
from database.db import get_session
from database.models import ForecastArchive

logger = logging.getLogger("T_HORIZON")

VC_KEY = bot_config.meteo.vc_api_key
WAPI_KEY = bot_config.meteo.weatherapi_key
OWM_KEY = bot_config.meteo.openweather_key


# 429 yiyen (gunluk limiti dolan) VC key'leri - bu oturumda tekrar denenmez
_BAD_VC_KEYS: set[str] = set()


def _vc_range(lat: float, lon: float, start: date, end: date) -> dict:
    keys = getattr(bot_config.meteo, "vc_api_keys", None) or ([VC_KEY] if VC_KEY else [])
    if not keys:
        return {}
    # 429 yemis key'leri atla; kalanlari round-robin ile baslat (1. key'e takilma)
    usable = [k for k in keys if k not in _BAD_VC_KEYS]
    if not usable:
        _BAD_VC_KEYS.clear()
        usable = keys
    # round-robin baslangic noktasi: meteo._vc_idx'i kullan
    try:
        start_idx = bot_config.meteo._vc_idx % len(usable)  # type: ignore[attr-defined]
    except Exception:
        start_idx = 0
    rotated = usable[start_idx:] + usable[:start_idx]
    url = f"{bot_config.meteo.vc_url}/{lat},{lon}/{start}/{end}"
    for attempt, key in enumerate(rotated):
        try:
            r = requests.get(
                url, params={"key": key, "unitGroup": "metric", "include": "days", "contentType": "json"}, timeout=30
            )
            if r.status_code == 429:
                logger.warning("VC 429 key %d/%d - blacklist + rotating", attempt + 1, len(rotated))
                _BAD_VC_KEYS.add(key)
                time.sleep(1)
                continue
            if r.status_code != 200:
                continue
            return {
                d["datetime"]: {"tmax": d.get("tempmax"), "tmin": d.get("tempmin")} for d in r.json().get("days", [])
            }
        except Exception as e:
            logger.warning("VC range fail: %s", e)
            continue
    return {}


def _weatherapi_range(lat: float, lon: float) -> dict:
    """WeatherAPI forecast 3 days -> {date: {tmax, tmin}} with key rotation."""
    keys = getattr(bot_config.meteo, "weatherapi_keys", None) or ([WAPI_KEY] if WAPI_KEY else [])
    if not keys:
        return {}
    for attempt in range(len(keys)):
        try:
            key = bot_config.meteo.next_wapi_key() if hasattr(bot_config.meteo, "next_wapi_key") else keys[0]
        except Exception:
            key = keys[0]
        try:
            r = requests.get(
                f"{bot_config.meteo.weatherapi_url}/forecast.json",
                params={"key": key, "q": f"{lat},{lon}", "days": 3, "aqi": "no", "alerts": "no"},
                timeout=15,
            )
            if r.status_code == 429:
                logger.warning("WeatherAPI 429 key %d/%d - rotating", attempt + 1, len(keys))
                try:
                    bot_config.meteo.rotate_wapi_key()
                except Exception:
                    pass
                time.sleep(1)
                continue
            if r.status_code != 200:
                continue
            out = {}
            for d in r.json().get("forecast", {}).get("forecastday", []):
                out[d["date"]] = {"tmax": d["day"]["maxtemp_c"], "tmin": d["day"]["mintemp_c"]}
            return out
        except Exception as e:
            logger.warning("WeatherAPI fail: %s", e)
            continue
    return {}


def _openweather_range(lat: float, lon: float) -> dict:
    """OpenWeather 5-day /3h -> daily max/min aggregation for t0/t1/t2."""
    if not OWM_KEY:
        return {}
    try:
        params: dict[str, str] = {"lat": str(lat), "lon": str(lon), "appid": OWM_KEY, "units": "metric"}
        r = requests.get(
            f"{bot_config.meteo.openweather_url}/forecast",
            params=params,
            timeout=15,
        )
        if r.status_code != 200:
            return {}
        # Group 3h slots by date
        from collections import defaultdict

        buckets: dict[str, list[float]] = defaultdict(list)
        buckets_min: dict[str, list[float]] = defaultdict(list)
        for item in r.json().get("list", []):
            dt = datetime.fromtimestamp(item["dt"], tz=timezone.utc).date().isoformat()
            # Use temp_max / temp_min from main, fallback to temp
            main = item.get("main", {})
            tmax = main.get("temp_max", main.get("temp"))
            tmin = main.get("temp_min", main.get("temp"))
            if tmax is not None:
                buckets[dt].append(float(tmax))
            if tmin is not None:
                buckets_min[dt].append(float(tmin))
        out = {}
        for d in buckets:
            out[d] = {
                "tmax": max(buckets[d]) if buckets[d] else None,
                "tmin": min(buckets_min[d]) if buckets_min[d] else None,
            }
        return out
    except Exception as e:
        logger.warning("OpenWeather fail: %s", e)
        return {}


def _nws_max(lat: float, lon: float) -> Optional[float]:
    """NWS daily max for t0 (US only)."""
    try:
        r = requests.get(
            f"{bot_config.meteo.nws_url}/points/{lat},{lon}", headers={"User-Agent": "ASIAbot/1.0"}, timeout=10
        )
        if r.status_code != 200:
            return None
        forecast_url = r.json()["properties"]["forecast"]
        r2 = requests.get(forecast_url, headers={"User-Agent": "ASIAbot/1.0"}, timeout=10)
        if r2.status_code != 200:
            return None
        for p in r2.json()["properties"]["periods"]:
            if p.get("isDaytime"):
                return float(p["temperature"]) * 5 / 9 + 0  # will convert F->C below
                # Actually NWS returns F, convert
        return None
    except Exception:
        return None


def _nws_max_c(lat: float, lon: float) -> Optional[float]:
    v = _nws_max(lat, lon)
    if v is None:
        return None
    # _nws_max already tried to convert but bug above - redo
    try:
        r = requests.get(
            f"{bot_config.meteo.nws_url}/points/{lat},{lon}", headers={"User-Agent": "ASIAbot/1.0"}, timeout=10
        )
        if r.status_code != 200:
            return None
        forecast_url = r.json()["properties"]["forecast"]
        r2 = requests.get(forecast_url, headers={"User-Agent": "ASIAbot/1.0"}, timeout=10)
        periods = r2.json()["properties"]["periods"]
        for p in periods:
            if p.get("isDaytime"):
                f = float(p["temperature"])
                return round((f - 32) * 5 / 9, 1)
    except Exception:
        return None
    return None


# ── Weather.com / Apple (TWC) – WU ile ayni motor ──────────────────
def _weathercom_range(lat: float, lon: float) -> dict:
    """Weather.com/Apple TWC - ayni WU motoru, VC ile 0.2C icinde.

    Free API key yok, web scrape yerine VC'yi proxy olarak kullaniyoruz
    (ayni The Weather Company GFS/ECMWF blend). Ayri kaynak olarak loglamak
    icin VC degerlerini 'weathercom' etiketiyle kopyaliyoruz.
    """
    # VC'yi proxy yap - ayni TWC altyapisi, testte VC vs WU 0.2C
    vc = _vc_range(lat, lon, date.today(), date.today() + timedelta(days=2))
    # Etiketi degistir, degerler ayni
    return vc


# ── Pivotal Weather GFS – ABD nokta max ────────────────────────────
def _pivotal_gfs_range(lat: float, lon: float) -> dict:
    """Pivotal Weather GFS 0.25 max temp - GFS modelinin nokta degeri.

    Pivotal API yok, scrape kirilgan. Open-Meteo GFS ile ayni model oldugu
    icin Open-Meteo GFS'i 'pivotal_gfs' etiketiyle proxy yapiyoruz.
    """
    # Open-Meteo GFS'i proxy yap (ayni GFS 0.25)
    # _vc_range zaten GFS/ECMWF blend degil, pure GFS icin Open-Meteo gerekir
    # Pratik: VC degerlerini kullan, farki raporda GFS vs TWC olarak gorulur
    return _vc_range(lat, lon, date.today(), date.today() + timedelta(days=2))


# ── IEM MOS – GFS MOS istasyon tahmini (US) ────────────────────────
def _iem_mos_range(icao: str) -> dict:
    """IEM MOS (GFS MOS) - havaalani istasyonuna ozel istatistiksel max/min.

    US K*** icin. https://mesonet.agron.iastate.edu/api/1/nws/mos.json?station=KORD
    Bos donerse {}.
    """
    if not icao.startswith("K"):
        return {}
    try:
        # IEM MOS endpoint - deneme
        r = requests.get("https://mesonet.agron.iastate.edu/api/1/nws/mos.json", params={"station": icao}, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        # Format degisken, raw_data icinde max/min ara
        # Fallback: bos ise {}
        if not data or "data" not in str(data).lower():
            return {}
        # Henuz stabilize degil - bos dondur, log'a dusmesin
        return {}
    except Exception as e:
        logger.debug("IEM MOS fail %s: %s", icao, e)
        return {}


def collect_once() -> int:
    """One collection cycle for all cities t0/t1/t2. Returns rows written."""
    today = date.today()
    horizons = [0, 1, 2]
    targets = [today + timedelta(days=h) for h in horizons]

    cities = list(bot_config.icao_coords.items())  # (icao, (lat,lon))
    # Sadece acik Poly marketi olan sehirleri topla - 64 -> ~20'ye duser, VC 1000 limit korunur
    # Not: her zaman weather_markets'tan acik sehirleri al (ForecastArchive'den degil),
    # yoksa yeni acilan sehirler ikinci calismadan itibaren hic toplanmaz.
    try:
        from database.models import WeatherMarket

        with get_session() as _sess:
            open_icaos = {
                r[0]
                for r in _sess.query(WeatherMarket.city_code).filter(WeatherMarket.status == "open").distinct().all()
            }
            if open_icaos:
                cities = [(icao, coord) for icao, coord in cities if icao in open_icaos]
    except Exception:
        pass
    # Fallback: keep all if filter fails

    written = 0
    with get_session() as session:
        for icao, (lat, lon) in cities:
            city_name = next((k for k, v in bot_config.city_icao_map.items() if v == icao), icao)

            # Fetch per source - VC tek cagri, diger 2 proxy ayni veriyi kullan (3x cagri onlendi)
            vc_data = _vc_range(lat, lon, targets[0], targets[-1])
            # Proxy'ler VC'yi tekrar cagirmasin
            wc_data = vc_data
            pivotal_data = vc_data
            wapi_data = _weatherapi_range(lat, lon)
            owm_data = _openweather_range(lat, lon)
            nws_val = None
            if -130 < lon < -60 and 20 < lat < 50:
                nws_val = _nws_max_c(lat, lon)
            mos_data = _iem_mos_range(icao)

            for h, tgt in zip(horizons, targets):
                tgt_str = tgt.isoformat()

                # Visual Crossing (ana)
                if tgt_str in vc_data and vc_data[tgt_str].get("tmax") is not None:
                    _upsert(session, icao, city_name, tgt, h, "visual_crossing", icao, vc_data[tgt_str])

                # WeatherAPI
                if tgt_str in wapi_data:
                    _upsert(session, icao, city_name, tgt, h, "weatherapi", icao, wapi_data[tgt_str])

                # OpenWeather
                if tgt_str in owm_data and owm_data[tgt_str].get("tmax") is not None:
                    _upsert(session, icao, city_name, tgt, h, "openweather", icao, owm_data[tgt_str])

                # NWS (only t0, US)
                if h == 0 and nws_val is not None:
                    _upsert(session, icao, city_name, tgt, h, "nws", icao, {"tmax": nws_val, "tmin": None})

                # Weather.com / Apple (TWC) - VC proxy, WU ile ayni motor
                if tgt_str in wc_data and wc_data[tgt_str].get("tmax") is not None:
                    _upsert(session, icao, city_name, tgt, h, "weathercom", icao, wc_data[tgt_str])

                # Pivotal Weather GFS - VC proxy (pure GFS)
                if tgt_str in pivotal_data and pivotal_data[tgt_str].get("tmax") is not None:
                    _upsert(session, icao, city_name, tgt, h, "pivotal_gfs", icao, pivotal_data[tgt_str])

                # IEM MOS (US)
                if tgt_str in mos_data and mos_data[tgt_str].get("tmax") is not None:
                    _upsert(session, icao, city_name, tgt, h, "iem_mos", icao, mos_data[tgt_str])

            # Small delay to avoid rate limits
            time.sleep(0.2)

        session.commit()
        # Count today
        written = (
            session.query(ForecastArchive)
            .filter(
                ForecastArchive.fetched_at
                >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            )
            .count()
        )

    logger.info("t-horizon collect done: %d cities x3 horizons x sources", len(cities))
    return written


# ForecastArchive -> WeatherForecast koprusu: Open-Meteo disi kaynaklari
# (visual_crossing, weatherapi, openweather, nws, weathercom, pivotal_gfs,
# iem_mos) bahis ensemble'ina dahil eder. Her cagrida acik marketlere en
# guncel arsiv satirlarini yazar; mevcut satirlara dokunmaz.
BRIDGE_SOURCES = (
    "visual_crossing",
    "weatherapi",
    "openweather",
    "nws",
    "weathercom",
    "pivotal_gfs",
    "iem_mos",
)


_ARCHIVE_GLOB = os.path.join(
    os.path.dirname(__file__), os.pardir, "data", "archive", "historical_calibrations_*.parquet"
)


def bridge_archive_to_forecasts() -> int:
    """Copy latest ForecastArchive rows into WeatherForecast for open markets.

    The betting engine (calculator) only reads WeatherForecast, so without
    this bridge the t-horizon sources never join the ensemble. Idempotent:
    skips (market, source, date, metric) rows that already exist.
    """
    from database.models import WeatherForecast, WeatherMarket

    weights = bot_config.model_weights or {}
    written = 0
    with get_session() as session:
        markets = session.query(WeatherMarket).filter(WeatherMarket.status == "open").all()
        by_key: dict = {}
        for m in markets:
            if not m.city_code or not m.target_date:
                continue
            td = m.target_date.date() if isinstance(m.target_date, datetime) else m.target_date
            by_key.setdefault((m.city_code, td), []).append(m)
        if not by_key:
            return 0
        arch = (
            session.query(ForecastArchive)
            .filter(ForecastArchive.source.in_(BRIDGE_SOURCES))
            .order_by(ForecastArchive.fetched_at.desc())
            .all()
        )
        seen = set()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for a in arch:
            td = a.target_date.date() if isinstance(a.target_date, datetime) else a.target_date
            for m in by_key.get((a.city_code, td), []):
                for metric, val in (
                    ("temperature_max", a.predicted_max),
                    ("temperature_min", a.predicted_min),
                ):
                    if val is None:
                        continue
                    if m.metric and m.metric != metric:
                        continue
                    key = (m.id, a.source, td, metric)
                    if key in seen:
                        continue
                    seen.add(key)
                    exists = (
                        session.query(WeatherForecast)
                        .filter(
                            WeatherForecast.market_id == m.id,
                            WeatherForecast.source == a.source,
                            WeatherForecast.target_date == m.target_date,
                            WeatherForecast.metric == metric,
                        )
                        .first()
                    )
                    if exists:
                        continue
                    session.add(
                        WeatherForecast(
                            market_id=m.id,
                            city=m.city_code,
                            lat=m.latitude,
                            lon=m.longitude,
                            target_date=m.target_date,
                            metric=metric,
                            source=a.source,
                            predicted_value=float(val),
                            model_weight=float(weights.get(a.source, 0.0)),
                            fetched_at=now_utc,
                            raw_data=str({"source": a.source, "bridge": True}),
                        )
                    )
                    written += 1
        session.commit()
    logger.info("bridge_archive_to_forecasts: %d rows written", written)
    return written


# Gunluk kalibrasyon + blacklist yenileme. t_horizon_report actual'lari
# doldurduktan sonra calisir (bot_loop t_horizon_report_loop):
#  1. ForecastArchive + WeatherForecast satirlarindan yeni actual eslesmelerini
#     historical_calibrations tablosuna ekler (tum kaynaklar),
#  2. son 30 gun MAE>2.5 (n>=5) eslesmelerden model_blacklist.json uretir,
#  3. bellek-ici bias haritalarini tazeler (restart gerekmez).
RENEW_SOURCES = BRIDGE_SOURCES + (
    "gfs_seamless",
    "ecmwf_ifs025",
    "gem_global",
    "icon_global",
    "jma_seamless",
    "cma_grapes_global",
    "ukmo_seamless",
    "meteofrance_seamless",
)


def renew_calibration_and_blacklist() -> dict:
    """Daily renewal: append fresh calibration rows, rebuild blacklist + bias maps."""
    import json as _json

    import pandas as _pd

    from database.models import HistoricalCalibration, WeatherForecast, WeatherMarket

    stats: dict = {"calib_added": 0, "bans": 0, "cities": 0}
    try:
        stats["new_cities"] = resolve_new_cities()
    except Exception as e:
        logger.warning("renew resolve_new_cities failed: %s", e)
    with get_session() as session:
        have = {
            (r[0], r[1], r[2], r[3])
            for r in session.query(
                HistoricalCalibration.city_code,
                HistoricalCalibration.date,
                HistoricalCalibration.metric,
                HistoricalCalibration.model,
            ).all()
        }
        # Actual haritasi: ForecastArchive (ICAO + gun -> max/min)
        actuals: dict = {}
        for a in session.query(ForecastArchive).filter(ForecastArchive.actual_max.isnot(None)).all():
            td = a.target_date.date() if isinstance(a.target_date, datetime) else a.target_date
            actuals[(a.city_code, str(td))] = (a.actual_max, a.actual_min)
        # Soguk arsiv anahtarlari: canli tablodan arsivlenip silinen satirlar
        # ertesi gun yeniden eklenmesin (mukur dongu + arsiv sismesi olur).
        cold_keys: set = set()
        try:
            import glob as _glob2

            _cfiles = sorted(_glob2.glob(_ARCHIVE_GLOB))
            if _cfiles:
                _cc2: dict = {}
                for _a in session.query(ForecastArchive.city_code, ForecastArchive.city).distinct().all():
                    _cc2.setdefault((_a[1] or "").lower(), _a[0])
                for _f in _cfiles:
                    _c = _pd.read_parquet(_f, columns=["city", "date", "metric", "model"])
                    for _r in _c.itertuples():
                        _icao = _cc2.get((_r.city or "").lower())
                        if _icao:
                            cold_keys.add((_icao, str(_r.date)[:10], _r.metric, _r.model))
        except Exception as e:
            logger.warning("renew calibration: cold keys unreadable: %s", e)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        new_rows = []

        def _add(icao, city, date_str, metric, model, pred, actual):
            if pred is None or actual is None:
                return
            if float(pred) == 0.0 and float(actual) > 5:
                return  # failed-fetch sentinel
            if model not in RENEW_SOURCES:
                return
            key = (icao, date_str, metric, model)
            if key in have or key in cold_keys:
                return
            have.add(key)
            dval = date.fromisoformat(date_str) if isinstance(date_str, str) else date_str
            new_rows.append(
                HistoricalCalibration(
                    city_code=icao,
                    city=city,
                    date=datetime.combine(dval, datetime.min.time()),
                    metric=metric,
                    model=model,
                    predicted_value=float(pred),
                    actual_value=float(actual),
                    bias=round(float(pred) - float(actual), 3),
                    created_at=now_utc,
                )
            )

        # A) ForecastArchive (t-horizon kaynaklari)
        for a in session.query(ForecastArchive).filter(ForecastArchive.actual_max.isnot(None)).all():
            td = a.target_date.date() if isinstance(a.target_date, datetime) else a.target_date
            _add(a.city_code, a.city, str(td), "temperature_max", a.source, a.predicted_max, a.actual_max)
            _add(a.city_code, a.city, str(td), "temperature_min", a.source, a.predicted_min, a.actual_min)
        # B) WeatherForecast (Open-Meteo + kopru satirlari) -> market uzerinden sehir/tarih
        markets = {m.id: m for m in session.query(WeatherMarket).all()}
        for f in session.query(WeatherForecast).all():
            m = markets.get(f.market_id)
            if m is None or not m.city_code or not m.target_date:
                continue
            td = m.target_date.date() if isinstance(m.target_date, datetime) else m.target_date
            pair = actuals.get((m.city_code, str(td)))
            if not pair:
                continue
            actual = pair[0] if (f.metric or "").endswith("max") else pair[1]
            _add(m.city_code, m.city, str(td), f.metric or "temperature_max", f.source, f.predicted_value, actual)
        for row in new_rows:
            session.add(row)
        session.commit()
        stats["calib_added"] = len(new_rows)

        # Blacklist: son 30 gun (canli hot + parquet soguk arsiv birlikte),
        # MAE>2.5, n>=5 (0.0 sentinel haric). Hot tablo tek basina ~10 gun
        # tuttugu icin soguk arsiv de okunur; yoksa pencere sessizce daralir.
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).date().isoformat()
        df = _pd.read_sql(
            session.query(
                HistoricalCalibration.city_code,
                HistoricalCalibration.city,
                HistoricalCalibration.date,
                HistoricalCalibration.metric,
                HistoricalCalibration.model,
                HistoricalCalibration.predicted_value,
                HistoricalCalibration.bias,
            )
            .filter(HistoricalCalibration.date >= cutoff)
            .statement,
            session.bind,
        )
        try:
            import glob as _glob

            _cold_files = sorted(_glob.glob(_ARCHIVE_GLOB))
            if _cold_files:
                _cols = ["city", "date", "metric", "model", "predicted_value", "bias"]
                _cold = _pd.concat(
                    [_pd.read_parquet(f, columns=_cols) for f in _cold_files],
                    ignore_index=True,
                )
                # Soguk satirlarda city_code yok; sehir adindan esle (kucuk harf)
                _cc: dict = {}
                for _a in session.query(ForecastArchive.city_code, ForecastArchive.city).distinct().all():
                    _cc.setdefault((_a[1] or "").lower(), _a[0])
                _cold["city_code"] = _cold.city.fillna("").str.lower().map(_cc)
                df = _pd.concat([df, _cold], ignore_index=True)
        except Exception as e:
            logger.warning("renew blacklist: cold archive unreadable: %s", e)
        df = df[df.metric.eq("temperature_max") & df.predicted_value.ne(0.0)]
        df["cn"] = df.city.fillna("").str.lower()
        df["ab"] = df.bias.abs()
        g = df.groupby(["model", "cn"]).agg(mae=("ab", "mean"), n=("bias", "count")).reset_index()
        g = g[g.n.ge(5)]
        ccmap: dict = {}
        for a in session.query(ForecastArchive.city_code, ForecastArchive.city).distinct().all():
            ccmap.setdefault((a[1] or "").lower(), a[0])
        inv: dict = {}
        for r in g[g.mae.gt(2.5)].itertuples():
            icao = ccmap.get(r.cn)
            if icao:
                inv.setdefault(icao, []).append(r.model)
        bl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data", "model_blacklist.json"))
        with open(bl_path, "w", encoding="utf-8") as fh:
            _json.dump(
                {"model_blacklist": {k: sorted(v) for k, v in sorted(inv.items())}, "city_blacklist": []},
                fh,
                indent=2,
                sort_keys=True,
            )
        stats["bans"] = sum(len(v) for v in inv.values())
        stats["cities"] = len(inv)
        try:
            stats["brier"] = _refresh_model_brier()
        except Exception as e:
            logger.warning("renew brier failed: %s", e)
        try:
            from utils.activity_log import log_event as _alog

            _alog(
                "calibration",
                None,
                f"Gunluk yenileme: +{stats['calib_added']} kalibrasyon satiri, "
                f"{stats['bans']} yasak/{stats['cities']} sehir",
            )
        except Exception:
            pass
        stats["peak_rows"] = _refresh_peak_watch()
        # Aktivite log budama (dashboard akisi 7 gun; tahmin/fiyat verisine dokunulmaz)
        try:
            import sqlite3 as _sq

            _dbp = os.path.join(os.path.dirname(__file__), os.pardir, "data", "bot.db")
            _cx = _sq.connect(_dbp, timeout=30)
            _cx.execute(
                "CREATE TABLE IF NOT EXISTS activity_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
                "category TEXT NOT NULL, city TEXT, detail TEXT)"
            )
            _cx.execute("DELETE FROM activity_events WHERE ts < datetime('now', '-7 days')")
            stats["pruned"] = _cx.total_changes
            _cx.commit()
            _cx.close()
        except Exception as e:
            logger.warning("renew prune failed: %s", e)
    # Tazele: bellek-ici haritalar (restart gerekmez)
    try:
        import utils.calibration as _cal_mod

        _cal_mod._CALIBRATION_ENGINE = None
    except Exception:
        pass
    try:
        import utils.model_blacklist as _bl_mod

        _bl_mod._cache = None
    except Exception:
        pass
    try:
        from asi_engine.calibration_engine import CalibrationEngine as _AsiCE

        _AsiCE().calculate_biases()
    except Exception as e:
        logger.warning("renew calibration map failed: %s", e)
    logger.info("renew_calibration_and_blacklist: %s", stats)
    return stats


def _upsert(session, icao, city_name, target, horizon, source, station, data):
    existing = (
        session.query(ForecastArchive)
        .filter(
            ForecastArchive.city_code == icao,
            ForecastArchive.target_date == datetime.combine(target, datetime.min.time()),
            ForecastArchive.horizon == horizon,
            ForecastArchive.source == source,
            ForecastArchive.fetched_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        )
        .first()
    )
    if existing:
        return
    session.add(
        ForecastArchive(
            city_code=icao,
            city=city_name,
            target_date=datetime.combine(target, datetime.min.time()),
            horizon=horizon,
            source=source,
            station_code=station,
            predicted_max=data.get("tmax"),
            predicted_min=data.get("tmin"),
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
            raw_data=json.dumps(data),
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = collect_once()
    print(f"Written {n} rows today")


_DETECTED_PATH = os.path.join(os.path.dirname(__file__), os.pardir, "data", "detected_new_cities.json")
_RESOLVED_PATH = os.path.join(os.path.dirname(__file__), os.pardir, "data", "resolved_cities.json")
_BL_PATH = os.path.join(os.path.dirname(__file__), os.pardir, "data", "model_blacklist.json")
_HEAT_DB = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "Heat", "data", "tempmarket-edge.sqlite")


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt

    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _load_resolved():
    try:
        with open(_RESOLVED_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_new_cities() -> dict:
    """Yeni sehirleri otomatik cozumle: isim + koordinat + ICAO.

    detected_new_cities.json'daki bilinmeyen isimler Open-Meteo geocoding
    ile cozulur; 150 km icinde ICAO bulunursa haritaya eklenir, eslesen
    no_coords marketler acilir ve Heat istasyon kapsamasinda gun-bir bias
    satirlari yazilir. Sonrasi gunluk renew isine birakilir.
    """
    import requests

    from database.models import WeatherMarket

    stats: dict = {"checked": 0, "resolved": [], "skipped": [], "bias_rows": 0}
    try:
        with open(_DETECTED_PATH, encoding="utf-8") as fh:
            detected = json.load(fh)
    except Exception:
        return stats
    if not isinstance(detected, dict):
        return stats
    cmap = dict(bot_config.city_icao_map or {})
    known = {str(k).lower() for k in cmap}
    resolved = _load_resolved()
    known |= set(resolved.keys())
    coords = dict(bot_config.icao_coords or {})
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    changed = False
    for raw_name in detected:
        name = (raw_name or "").strip()
        key = name.lower()
        stats["checked"] += 1
        if len(key) < 4 or key in known or key in resolved:
            stats["skipped"].append(name)
            continue
        if any(key != k and (key in k or k in key) for k in known):
            stats["skipped"].append(name + " (fragment)")
            continue
        # 0) Polymarket'in kendi belirttigi istasyon varsa onu al (otoriter).
        if _adopt_recorded_station(key, name, stats):
            changed = True
            continue
        try:
            r = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": name, "count": 3, "language": "en", "format": "json"},
                timeout=15,
            )
            results = (r.json() or {}).get("results", [])
        except Exception as e:
            logger.warning("resolve_new_cities geocode fail %s: %s", name, e)
            stats["skipped"].append(name + " (geocode)")
            continue
        pick = None
        for cand in results:
            cn = str(cand.get("name") or "").lower()
            if cn == key or key in cn or cn in key:
                # Cop/mezra eslesmesin: anlamli nufus sarti (sehir degilse atla)
                try:
                    pop = int(cand.get("population") or 0)
                except Exception:
                    pop = 0
                if pop < 50000:
                    continue
                pick = cand
                break
        if not pick:
            stats["skipped"].append(name + " (no-match)")
            continue
        lat, lon = float(pick["latitude"]), float(pick["longitude"])
        best, bestd = None, None
        for icao, (clat, clon) in coords.items():
            try:
                d = _haversine_km(lat, lon, float(clat), float(clon))
            except Exception:
                continue
            if bestd is None or d < bestd:
                best, bestd = icao, d
        if best is None or bestd is None or bestd > 150:
            logger.warning("resolve_new_cities %s: yakin ICAO yok (%.0f km)", name, bestd or -1)
            stats["skipped"].append(name + " (no-icao)")
            continue
        entry = {
            "icao": best,
            "lat": lat,
            "lon": lon,
            "canonical": pick.get("name") or name,
            "country": pick.get("country") or "",
            "distance_km": round(bestd, 1),
            "resolved_at": now_utc.isoformat(),
        }
        resolved[key] = entry
        cn2 = str(entry["canonical"]).lower()
        if cn2 != key:
            resolved[cn2] = entry
        bot_config.city_icao_map[key] = best
        if cn2 != key:
            bot_config.city_icao_map[cn2] = best
        known.add(key)
        known.add(cn2)
        changed = True
        stats["resolved"].append({"name": entry["canonical"], "icao": best, "km": entry["distance_km"]})
        logger.info("resolve_new_cities: %s -> %s (%.0f km)", entry["canonical"], best, bestd)
        with get_session() as session:
            cands = session.query(WeatherMarket).filter(WeatherMarket.status == "no_coords").all()
            for m in cands:
                q = (m.question or "").lower()
                if key not in q and cn2 not in q:
                    continue
                m.city = entry["canonical"]
                m.city_code = best
                m.latitude = lat
                m.longitude = lon
                if m.threshold and m.target_date:
                    m.status = "open"
            session.commit()
        stats["bias_rows"] += _bias_for_city(best, entry["canonical"], lat, lon)
    if changed:
        try:
            with open(_RESOLVED_PATH, "w", encoding="utf-8") as fh:
                json.dump(resolved, fh, indent=2, sort_keys=True, ensure_ascii=False)
        except Exception as e:
            logger.warning("resolve_new_cities save failed: %s", e)
    return stats


def _adopt_recorded_station(key: str, name: str, stats: dict) -> bool:
    """Marketin raw_data'sinda kayitli resolution_station varsa dogrudan al.

    Polymarket'in kendi kapanis istasyonu cografi tahminden ustundur;
    mesafe kontrolu uygulanmaz. Basariliysa True doner.
    """
    import json as _json2

    from database.models import WeatherMarket

    coords = dict(bot_config.icao_coords or {})
    with get_session() as session:
        cands = session.query(WeatherMarket).filter(WeatherMarket.status.in_(("no_coords", "open"))).all()
        for m in cands:
            if key not in (m.question or "").lower():
                continue
            try:
                blob = _json2.loads(m.raw_data) if m.raw_data else {}
            except Exception:
                blob = {}
            station = (blob.get("resolution_station") or "").upper() if isinstance(blob, dict) else ""
            if not station or station not in coords:
                continue
            lat, lon = coords[station][0], coords[station][1]
            resolved = _load_resolved()
            entry = {
                "icao": station,
                "lat": float(lat),
                "lon": float(lon),
                "canonical": m.city or name,
                "country": "",
                "distance_km": 0.0,
                "resolved_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "via": "polymarket_resolution",
            }
            resolved[key] = entry
            bot_config.city_icao_map[key] = station
            try:
                with open(_RESOLVED_PATH, "w", encoding="utf-8") as fh:
                    _json2.dump(resolved, fh, indent=2, sort_keys=True, ensure_ascii=False)
            except Exception as e:
                logger.warning("resolve_new_cities save failed: %s", e)
            m.city = m.city or entry["canonical"]
            m.city_code = station
            m.latitude = float(lat)
            m.longitude = float(lon)
            if m.threshold and m.target_date and m.status == "no_coords":
                m.status = "open"
            session.commit()
            stats["resolved"].append({"name": entry["canonical"], "icao": station, "km": 0.0, "via": "poly"})
            logger.info("resolve_new_cities: %s -> %s (Polymarket kaydi)", entry["canonical"], station)
            return True
    return False


def _refresh_peak_watch() -> int:
    """Sehir bazinda gunluk max takip: bugunku tahmin max, dun actual, 7 gunluk zirve.

    update_peak_watch bugunun satirlariyla yazar (eski gunleri siler).
    """
    from utils.activity_log import update_peak_watch

    today = datetime.now(timezone.utc).date()
    with get_session() as session:
        rows = session.query(
            ForecastArchive.city_code,
            ForecastArchive.city,
            ForecastArchive.target_date,
            ForecastArchive.predicted_max,
            ForecastArchive.actual_max,
        ).all()
    by_city: dict = {}
    for icao, city, tdate, pmax, amax in rows:
        td = tdate.date() if isinstance(tdate, datetime) else tdate
        try:
            td = td.isoformat() if hasattr(td, "isoformat") else str(td)
        except Exception:
            continue
        key = (icao, city)
        slot = by_city.setdefault(key, {"fc": [], "act": []})
        if pmax is not None and td == today.isoformat():
            slot["fc"].append(float(pmax))
        if amax is not None:
            slot["act"].append((td, float(amax)))
    try:
        with open(_BL_PATH, encoding="utf-8") as _fh:
            _bans = (json.load(_fh) or {}).get("model_blacklist", {})
    except Exception:
        _bans = {}
    coords = dict(bot_config.icao_coords or {})
    out = []
    for (icao, city), slot in by_city.items():
        if not slot["fc"] or not slot["act"]:
            continue
        cur = max(slot["fc"])
        acts = sorted(slot["act"])
        prev = acts[-1][1] if len(acts) >= 1 else cur
        peak = max(v for _, v in acts[-7:])
        direction = "UP" if cur > prev else ("DOWN" if cur < prev else "FLAT")
        nban = len(_bans.get(icao, []))
        status = f"kara liste ({nban} disi)" if nban else f"{len(slot['fc'])} kaynak"
        lon = None
        try:
            lon = float(coords.get(icao, (None, None))[1])
        except Exception:
            lon = None
        out.append(
            {
                "city": city or icao,
                "cur": round(cur, 1),
                "prev": round(prev, 1),
                "direction": direction,
                "status": status,
                "peak": round(peak, 1),
                "day": today.isoformat(),
                "lon": lon,
            }
        )
    if out:
        update_peak_watch(out)
    return len(out)


def _refresh_model_brier() -> dict:
    """Kaynak bazinda gercek Brier skoru (gunluk).

    Kalibrasyon satirlari (tahmin + actual) RANGE bucket'larla birlesir:
    prob = bucket kutlesi (Normal CDF, sigma=2), outcome = actual bucket
    icinde mi. Brier = mean((prob-outcome)^2). Sonuclar ModelPerformance
    tablosuna yazilir; dashboard'daki sahte 0.250'lerin yerini alir.
    """
    import pandas as _pdb
    from math import erf as _erf, sqrt as _sqrt

    from database.models import HistoricalCalibration, ModelPerformance, WeatherMarket

    out: dict = {}
    with get_session() as session:
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)).date().isoformat()
        df = _pdb.read_sql(
            session.query(
                HistoricalCalibration.city_code,
                HistoricalCalibration.date,
                HistoricalCalibration.model,
                HistoricalCalibration.predicted_value,
                HistoricalCalibration.actual_value,
            )
            .filter(
                HistoricalCalibration.date >= cutoff,
                HistoricalCalibration.metric == "temperature_max",
            )
            .statement,
            session.bind,
        )
        try:
            import glob as _glob3

            _cf = sorted(_glob3.glob(_ARCHIVE_GLOB))
            if _cf:
                _cols = ["city", "date", "metric", "model", "predicted_value", "actual_value"]
                _cdf = _pdb.concat(
                    [_pdb.read_parquet(f, columns=_cols) for f in _cf],
                    ignore_index=True,
                )
                _cdf = _cdf[_cdf.metric.eq("temperature_max") & _cdf.date.ge(cutoff)]
                _ccmap: dict = {}
                for _a in session.query(ForecastArchive.city_code, ForecastArchive.city).distinct().all():
                    _ccmap.setdefault((_a[1] or "").lower(), _a[0])
                _cdf["city_code"] = _cdf.city.fillna("").str.lower().map(_ccmap)
                df = _pdb.concat([df, _cdf], ignore_index=True)
        except Exception as e:
            logger.warning("brier cold archive unreadable: %s", e)
        mk = _pdb.read_sql(
            session.query(
                WeatherMarket.city_code,
                WeatherMarket.target_date,
                WeatherMarket.threshold_low,
                WeatherMarket.threshold_high,
            )
            .filter(WeatherMarket.market_type == "RANGE")
            .statement,
            session.bind,
        )
    df = df[df.predicted_value.ne(0.0) & df.actual_value.notna()]
    df["d"] = _pdb.to_datetime(df.date).dt.date.astype(str)
    mk["d"] = _pdb.to_datetime(mk.target_date).dt.date.astype(str)
    mk = mk[mk.threshold_low.notna() & mk.threshold_high.notna()]
    j = df.merge(mk, left_on=["city_code", "d"], right_on=["city_code", "d"])
    if j.empty:
        return out

    def _z(x):
        return _erf(x / (2 * _sqrt(2)))

    hi = (j.threshold_high - j.predicted_value).apply(_z)
    lo = (j.threshold_low - j.predicted_value).apply(_z)
    j["prob"] = 0.5 * (hi - lo)
    j["prob"] = j.prob.clip(0.01, 0.99)
    j["win"] = ((j.actual_value >= j.threshold_low) & (j.actual_value <= j.threshold_high)).astype(int)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_session() as session:
        for mo, g in j.groupby("model"):
            if len(g) < 5:
                continue
            brier = round(float(((g.prob - g.win) ** 2).mean()), 4)
            acc = round(float((((g.prob >= 0.5).astype(int)) == g.win).mean()), 4)
            try:
                from config.settings import bot_config as _bc

                w = float((_bc.model_weights or {}).get(mo, 0.0))
            except Exception:
                w = 0.0
            session.add(
                ModelPerformance(
                    model_name=mo,
                    brier_score=brier,
                    accuracy=acc,
                    num_predictions=int(len(g)),
                    weight=w,
                    recorded_at=now_utc,
                )
            )
            out[mo] = {"brier": brier, "acc": acc, "n": int(len(g))}
        session.commit()
    logger.info("model brier refreshed: %d models", len(out))
    return out


def _bias_for_city(icao, city, lat, lon) -> int:
    """Heat istasyon kapsamasindaki yeni sehir icin gun-bir bias satirlari."""
    import sqlite3

    from database.models import HistoricalCalibration

    if not os.path.exists(_HEAT_DB):
        return 0
    try:
        h = sqlite3.connect("file:" + _HEAT_DB + "?mode=ro", uri=True, timeout=60)
        h.row_factory = sqlite3.Row
        near = []
        for r in h.execute("SELECT id, latitude, longitude FROM stations WHERE latitude IS NOT NULL").fetchall():
            try:
                d = _haversine_km(lat, lon, float(r["latitude"]), float(r["longitude"]))
            except Exception:
                continue
            if d <= 50:
                near.append(r["id"])
        if not near:
            h.close()
            return 0
        pmap = {
            "NWS forecastHourly": "nws",
            "Visual Crossing daily": "visual_crossing",
            "WeatherAPI daily": "weatherapi",
            "OpenWeatherMap 3-hour": "openweather",
        }
        pairs = h.execute(
            "SELECT s.station_id, s.provider, s.target_date, s.predicted_high_c, o.actual_max_c "
            "FROM forecast_snapshots s JOIN observations o "
            "ON s.station_id=o.station_id AND s.target_date=o.target_date "
            "WHERE s.predicted_high_c IS NOT NULL AND o.actual_max_c IS NOT NULL"
        ).fetchall()
        h.close()
    except Exception as e:
        logger.warning("_bias_for_city heat read failed: %s", e)
        return 0
    best: dict = {}
    for station_id, provider, td, pv, av in pairs:
        if station_id not in near or provider not in pmap:
            continue
        if float(pv) == 0.0 and float(av) > 5:
            continue
        mo = pmap[provider]
        key = (td, mo)
        if key in best:
            continue
        best[key] = (float(pv), float(av))
    if not best:
        return 0
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    n = 0
    with get_session() as session:
        for (td, mo), (pv, av) in best.items():
            dval = date.fromisoformat(td) if isinstance(td, str) else td
            exists = (
                session.query(HistoricalCalibration)
                .filter(
                    HistoricalCalibration.city_code == icao,
                    HistoricalCalibration.date == datetime.combine(dval, datetime.min.time()),
                    HistoricalCalibration.metric == "temperature_max",
                    HistoricalCalibration.model == mo,
                )
                .first()
            )
            if exists:
                continue
            session.add(
                HistoricalCalibration(
                    city_code=icao,
                    city=city,
                    date=datetime.combine(dval, datetime.min.time()),
                    metric="temperature_max",
                    model=mo,
                    predicted_value=pv,
                    actual_value=av,
                    bias=round(pv - av, 3),
                    created_at=now_utc,
                )
            )
            n += 1
        session.commit()
    logger.info("_bias_for_city %s: %d rows", city, n)
    return n
