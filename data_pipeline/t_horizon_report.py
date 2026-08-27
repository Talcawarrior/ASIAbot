"""Gun sonu gerceklesen karsilastirma + kesisen gunler WU uyumu raporu.

Her gun 00:30 UTC'de dun'un actual'ini VC/IEM'den ceker, ForecastArchive
satirlarini doldurur, sonra kesisen horizon'larin WU ile uyumunu raporlar.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from collections import defaultdict

from database.db import get_session
from database.models import ForecastArchive
from utils.weather_sources import settlement_actual
from config.settings import bot_config

logger = logging.getLogger("T_HORIZON_REPORT")


def fill_actuals_for_date(target: date) -> int:
    """Dun icin actual MAX/MIN'i VC/IEM'den cekip ForecastArchive'a yaz.

    Idempotent: zaten actual_max dolu satirlari tekrar cagirmaz (sadece NULL
    olanlari doldurur). Boylece ayni sehir+gun icin tutarsiz actual degerleri
    olusmaz.
    """
    filled = 0
    with get_session() as session:
        tgt_dt = datetime.combine(target, datetime.min.time())
        rows = session.query(ForecastArchive.city_code).filter(ForecastArchive.target_date == tgt_dt).distinct().all()
        for (icao,) in rows:
            lat, lon = bot_config.icao_coords.get(icao, (None, None))
            if lat is None:
                continue
            # Tek seferde actual cek, sadece henuz dolu olmayan satirlara yaz
            recs = (
                session.query(ForecastArchive)
                .filter(
                    ForecastArchive.city_code == icao,
                    ForecastArchive.target_date == datetime.combine(target, datetime.min.time()),
                    ForecastArchive.actual_max.is_(None),
                )
                .all()
            )
            if not recs:
                continue
            actual, src = settlement_actual(icao, lat, lon, target)
            if actual is None:
                continue
            from utils.weather_sources import vc_daily

            vc = vc_daily(lat, lon, target)
            tmin = vc.get("tmin") if vc else None
            for rec in recs:
                rec.actual_max = actual
                rec.actual_min = tmin
                rec.actual_source = src
                if rec.predicted_max is not None and actual is not None:
                    rec.is_match = abs(rec.predicted_max - actual) <= 0.5
                filled += 1
        session.commit()
    logger.info("fill_actuals %s: %d rows", target, filled)
    return filled


def generate_report(days: int = 7) -> str:
    """Son `days` gun icin kesisen horizon raporu uret."""
    end = date.today() - timedelta(days=1)  # dun bitti
    start = end - timedelta(days=days - 1)

    # Detached-instance guvenli: ORM nesnelerini plain tuple'a cevir
    plain = []
    with get_session() as session:
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.min.time())
        rows = (
            session.query(ForecastArchive)
            .filter(
                ForecastArchive.target_date >= start_dt,
                ForecastArchive.target_date <= end_dt,
            )
            .order_by(
                ForecastArchive.city_code,
                ForecastArchive.target_date,
                ForecastArchive.horizon,
                ForecastArchive.source,
            )
            .all()
        )
        for r in rows:
            plain.append(
                {
                    "city_code": r.city_code,
                    "target_date": r.target_date.date().isoformat() if r.target_date else "",
                    "horizon": r.horizon,
                    "source": r.source,
                    "predicted_max": r.predicted_max,
                    "actual_max": r.actual_max,
                    "actual_source": r.actual_source,
                    "is_match": r.is_match,
                    "fetched_at": r.fetched_at.date().isoformat() if r.fetched_at else "?",
                }
            )
    rows = plain

    # Group: (city, target_date) -> list
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["city_code"], r["target_date"])].append(r)

    lines: list[str] = []
    lines.append(f"t0/t1/t2 Kesisen Gunler WU Uyumu Raporu ({start} -> {end})")
    lines.append("Kaynaklar: visual_crossing, weatherapi, openweather, nws (Wethr.net/polyweather yok)")
    lines.append("Match = |tahmin - WU actual| <= 0.5C")
    lines.append("")

    # Per city summary
    for (city_code, tgt_str), recs in sorted(grouped.items()):
        if not recs:
            continue
        actual = next((r["actual_max"] for r in recs if r["actual_max"] is not None), None)
        actual_src = next((r["actual_source"] for r in recs if r["actual_source"]), "-")
        lines.append(f"{city_code} {tgt_str}  WU actual {actual} ({actual_src})")
        # Table per horizon
        for h in [0, 1, 2]:
            horizon_recs = [r for r in recs if r["horizon"] == h]
            if not horizon_recs:
                continue
            for r in horizon_recs:
                pred = r["predicted_max"]
                match = "OK" if r["is_match"] else "SAPMA" if r["is_match"] is False else "?"
                fetched = r["fetched_at"]
                pred_s = f"{pred:5.1f}" if pred is not None else "  - "
                lines.append(f"  t{h} {r['source']:16s} {pred_s}C fetched {fetched} -> {match}")
        # Kesisen gun ozeti: ayni target icin t2/t1/t0'dan hangisi tuttu
        t0_ok = any(r["is_match"] for r in recs if r["horizon"] == 0 and r["is_match"])
        t1_ok = any(r["is_match"] for r in recs if r["horizon"] == 1 and r["is_match"])
        t2_ok = any(r["is_match"] for r in recs if r["horizon"] == 2 and r["is_match"])
        if any([t0_ok, t1_ok, t2_ok]):
            ozet = "Kesisen ozet: t0={} t1={} t2={}".format(
                "OK" if t0_ok else "SAPMA",
                "OK" if t1_ok else "SAPMA",
                "OK" if t2_ok else "SAPMA",
            )
            lines.append(ozet)
        lines.append("")

    # Global source basarisi
    total_by_source: dict[str, dict] = defaultdict(lambda: {"ok": 0, "total": 0})
    for r in rows:
        if r["is_match"] is not None and r["predicted_max"] is not None:
            total_by_source[r["source"]]["total"] += 1
            if r["is_match"]:
                total_by_source[r["source"]]["ok"] += 1
    lines.append("Kaynak Bazli 7 Gun Basari:")
    for src, v in sorted(total_by_source.items(), key=lambda x: x[1]["ok"] / max(x[1]["total"], 1), reverse=True):
        rate = v["ok"] / v["total"] * 100 if v["total"] else 0
        lines.append(f"  {src:16s} {v['ok']}/{v['total']} = {rate:.0f}%")

    report = "\n".join(lines)
    logger.info("\n%s", report)
    return report


def run_daily_job() -> str:
    """Dun'un actual'ini doldur ve rapor uret. Bot loop'tan cagrilir."""
    yesterday = date.today() - timedelta(days=1)
    fill_actuals_for_date(yesterday)
    return generate_report(days=7)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_daily_job())
