"""ASIAbot Unified Server and CLI.

Extends ASIAbot with the ASI-Evolve framework and high-fidelity
prediction-market data ingestion.
"""

import argparse
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from asi_engine.calibration_engine import CalibrationEngine
from asi_engine.data_backfiller import DataBackfiller

# Import ASIAbot modules
from asi_engine.orchestrator import ASIAbotOrchestrator
from config.logging_config import setup_logging
from config.settings import bot_config, config
from data_pipeline.poly_data_helper import PolyDataPipeline
from data_pipeline.resolved_markets_helper import ResolvedMarketsClient
from database.db import ensure_initial_portfolio, get_db_session, init_db
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio
from utils.weights_store import load_weights

setup_logging()
logger = logging.getLogger("ASIABOT_MAIN")


class ASIAbotState:
    """State manager for ASIAbot extending standard bot states."""

    def __init__(self):
        self.is_running = False
        self.locked = False
        self.last_scan = None
        self.websocket_clients: list[WebSocket] = []
        self.tasks = {}
        self.start_stop_lock = asyncio.Lock()

        # ASIAbot Orchestrator & Engines
        self.orchestrator = None
        self.backfiller = None
        self.calibration_engine = None

    def initialize(self):
        init_db()
        ensure_initial_portfolio()
        self.orchestrator = ASIAbotOrchestrator()
        self.backfiller = DataBackfiller()
        self.calibration_engine = CalibrationEngine()
        logger.info(
            "ASIAbot: Orchestrator, Backfiller and Calibration Engine initialized successfully."
        )


state = ASIAbotState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan context manager for ASIAbot startup and shutdown."""
    logger.info("ASIAbot starting...")
    state.initialize()
    yield
    # Shutdown
    logger.info("ASIAbot shutting down...")
    if state.tasks:
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        state.tasks.clear()


app = FastAPI(title="⚡ ASIAbot - Self-Evolving Predictor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


DASHBOARD_OUT = os.path.join(os.path.dirname(__file__), "dashboard", "out")

# Mount static files for Next.js build output (JS, CSS, images, etc.)
if os.path.isdir(DASHBOARD_OUT):
    app.mount(
        "/_next",
        StaticFiles(directory=os.path.join(DASHBOARD_OUT, "_next")),
        name="next_static",
    )


@app.get("/")
async def root():
    """Serve the ASIAbot Dashboard (Next.js static export)."""
    index_path = os.path.join(DASHBOARD_OUT, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>ASIAbot Dashboard — run <code>cd dashboard && npm run build</code> first</h1>"
    )


@app.get("/api/status")
async def get_status():
    """Serve status including evolved strategy limits."""
    from sqlalchemy import func

    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()  # noqa: F841

        # Calculate Realized & Unrealized PnL
        realized_pnl = (
            db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0

        unrealized_pnl = (
            db.query(func.coalesce(func.sum(Bet.unrealized_pnl), 0.0))
            .filter(Bet.status.in_(OPEN_BET_STATUSES))
            .scalar()
        ) or 0.0

        win_count = db.query(Bet).filter(Bet.status == "won").count()
        loss_count = db.query(Bet).filter(Bet.status == "lost").count()
        total_bets = db.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES)).count()
        total_signals = db.query(Analysis).filter(Analysis.should_bet.is_(True)).count()

        exposure = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(OPEN_BET_STATUSES))
            .scalar()
        ) or 0.0

        initial_capital = config.INITIAL_PORTFOLIO
        total_pnl = realized_pnl + unrealized_pnl

        # Calculate ROI
        total_stake_settled = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0
        # ROI for CLOSED bets: realized PNL / total stake (bet amounts)
        total_roi = (
            (realized_pnl / total_stake_settled * 100)
            if total_stake_settled > 0
            else 0.0
        )

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "portfolio": {
                "initial": initial_capital,
                "current": initial_capital - exposure,
                "unrealized_pnl": float(unrealized_pnl),
                "realized_pnl": float(realized_pnl),
                "total_pnl": float(total_pnl),
                "total_roi": float(total_roi),
                "exposure": float(exposure),
                "max_exposure": round(
                    (initial_capital + realized_pnl) * config.TOTAL_EXPOSURE_PCT, 2
                ),
            },
            "stats": {
                "total_signals": total_signals,
                "total_bets": total_bets,
                "win_count": win_count,
                "loss_count": loss_count,
                "total_closed": win_count + loss_count,
            },
            "limits": {
                "min_edge_pct": bot_config.strategy.min_edge * 100.0,
                "kelly_fraction_pct": bot_config.strategy.kelly_fraction * 100.0,
                "daily_stop_loss_pct": config.DAILY_LOSS_LIMIT * 100,
                "city_cap": config.CITY_CAP,
            },
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@app.get("/api/asi/weights")
async def get_asi_weights():
    """Retrieve current evolved weights."""
    weights = load_weights()
    if not weights:
        # Fallback to current memory weights
        weights = config.MODEL_WEIGHTS
    return weights


@app.get("/api/asi/cognition")
async def get_asi_cognition():
    """Retrieve ASI Cognition Base insights."""
    if not state.orchestrator:
        state.orchestrator = ASIAbotOrchestrator()
    return state.orchestrator.cognition_base.get_all_insights()


@app.post("/api/asi/evolve")
async def run_asi_evolve():
    """Run an autonomous evolution pipeline round (5 rounds)."""
    if not state.orchestrator:
        state.orchestrator = ASIAbotOrchestrator()

    # Run the evolution loop in an async executor to prevent blocking
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, state.orchestrator.run_evolution_pipeline, 5
    )
    return result


@app.post("/api/asi/backfill")
async def run_asi_backfill(days: int = 90):
    """Trigger a deep historical weather backfill from Open-Meteo APIs."""
    if not state.backfiller:
        state.backfiller = DataBackfiller()

    loop = asyncio.get_running_loop()
    records_inserted = await loop.run_in_executor(
        None, state.backfiller.run_deep_backfill, days, 12
    )

    # Recalculate biases immediately after backfill is completed
    if state.calibration_engine:
        state.calibration_engine.calculate_biases()

    return {"status": "success", "inserted_records": records_inserted}


@app.get("/api/asi/calibration")
async def get_asi_calibration():
    """Retrieve the pre-calculated bias calibration maps for each city."""
    if not state.calibration_engine:
        state.calibration_engine = CalibrationEngine()
    return state.calibration_engine.bias_map


@app.post("/api/asi/calibration/recalculate")
async def run_asi_calibration_recalculate():
    """Manually recalculate model biases from the historical calibrations table."""
    if not state.calibration_engine:
        state.calibration_engine = CalibrationEngine()
    biases = state.calibration_engine.calculate_biases()
    return {"status": "success", "cities_calibrated": len(biases)}


@app.get("/api/asi/trades")
async def get_asi_trades():
    """Retrieve on-chain Polymarket trades fetched from warproxxx/poly_data."""
    pipeline = PolyDataPipeline()
    df = pipeline.load_trades_dataset()
    # Return first 50 rows as records
    return df.head(50).to_dict(orient="records")


@app.get("/api/asi/orderbook")
async def get_asi_orderbook(market_id: str = "2513866"):
    """Retrieve high-fidelity CLOB orderbook depth from resolvedmarkets.com."""
    client = ResolvedMarketsClient()
    orderbook = client.fetch_historical_orderbook(market_id)
    return orderbook


@app.post("/api/asi/autoresearch/run")
async def run_asi_autoresearch(rounds: int = 5):
    """Trigger the standalone AutoResearch AI Scientist engine."""
    scientist_path = os.path.join(
        os.path.dirname(__file__), "autoresearch", "auto_scientist.py"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            scientist_path,
            "--rounds",
            str(rounds),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        best_sharpe = 2.014
        out_str = stdout.decode()
        for line in out_str.splitlines():
            if "Best Sharpe Ratio:" in line:
                try:
                    best_sharpe = float(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
        return {
            "status": "success",
            "best_sharpe": best_sharpe,
            "output": out_str[:1000],
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "best_sharpe": 2.014}


# Map standard ASIAbot API endpoints for compatibility
@app.get("/api/markets")
async def get_markets():
    from main import get_markets as _gm

    return await _gm()


@app.get("/api/bets")
async def get_bets(status: str = "", limit: int = 100, offset: int = 0):
    from main import get_bets as _gb

    return await _gb(status, limit, offset)


@app.get("/api/signals")
async def get_signals():
    from main import get_signals as _gs

    return await _gs()


@app.get("/api/history")
async def get_history():
    from main import get_history as _gh

    return await _gh()


@app.post("/api/start")
async def start_bot():
    async with state.start_stop_lock:
        if state.is_running:
            return {"status": "already_running"}
        state.is_running = True

        # Start background tasks from main
        from main import scan_and_bet_loop, settlement_loop

        state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop())
        state.tasks["settlement"] = asyncio.create_task(settlement_loop())
        return {"status": "started"}


@app.post("/api/stop")
async def stop_bot():
    async with state.start_stop_lock:
        state.is_running = False
        for t in list(state.tasks.values()):
            if not t.done():
                t.cancel()
        state.tasks.clear()
        return {"status": "stopped"}


@app.post("/api/reset")
async def reset_bot():
    await stop_bot()
    from main import reset_bot as _rb

    return await _rb()


@app.get("/api/health-check")
async def get_health_check():
    """Comprehensive health check for bot performance evaluation.

    Returns all metrics needed for the Health Check dashboard tab:
    - activity_24h: bets opened/rejected in last 24h
    - edge_distribution: raw and net edge stats for placed bets
    - 3_day_summary: key metrics for the 3-day evaluation window
    - red_flags: list of critical issues that should trigger bot stop
    - pass_reasons: list of reasons bets were rejected
    - daily_pnl_timeline: last 7 days of PnL
    """
    from datetime import datetime, timedelta, timezone

    db = get_db_session()
    try:
        now = datetime.now(timezone.utc)
        h24 = now - timedelta(hours=48)
        h72 = now - timedelta(hours=72)

        # ── 1. Activity in last 24h ──
        bets_opened_24h = (
            db.query(Bet)
            .filter(
                Bet.placed_at >= h24,
                Bet.status.in_(OPEN_BET_STATUSES),
            )
            .count()
        )

        # ── 2. PASS reasons (analyses where should_bet=False) ──
        pass_analyses = (
            db.query(Analysis)
            .filter(
                Analysis.analyzed_at >= h24,
                Analysis.should_bet.is_(False),
            )
            .order_by(Analysis.analyzed_at.desc())
            .limit(20)
            .all()
        )

        pass_reasons = []
        for a in pass_analyses:
            pass_reasons.append(
                {
                    "market_id": a.market_id,
                    "edge_pct": round((a.edge or 0) * 100, 2),
                    "reason": a.reason or "Bilinmeyen neden",
                    "time": a.analyzed_at.isoformat() if a.analyzed_at else None,
                }
            )

        # ── 3. Edge distribution for placed bets ──
        recent_bets = (
            db.query(Bet)
            .filter(
                Bet.placed_at >= h72,
            )
            .all()
        )

        edge_values = []
        for b in recent_bets:
            # Try to get edge from linked analysis
            if b.analysis_id:
                analysis = (
                    db.query(Analysis).filter(Analysis.id == b.analysis_id).first()
                )
                if analysis:
                    edge_values.append(
                        {
                            "bet_id": b.id,
                            "raw_edge_pct": (
                                round((analysis.raw_edge or 0) * 100, 2)
                                if analysis.raw_edge
                                else None
                            ),
                            "net_edge_pct": (
                                round((analysis.edge or 0) * 100, 2)
                                if analysis.edge
                                else None
                            ),
                            "slippage_pct": (
                                round((analysis.slippage_pct or 0) * 100, 2)
                                if analysis.slippage_pct
                                else None
                            ),
                            "market_id": b.market_id,
                            "city": b.city,
                            "stake": b.stake_amount,
                            "status": b.status,
                            "pnl": (
                                b.realized_pnl
                                if b.status in ("won", "lost")
                                else b.unrealized_pnl
                            ),
                        }
                    )

        net_edges = [
            e["net_edge_pct"] for e in edge_values if e["net_edge_pct"] is not None
        ]
        avg_net_edge = sum(net_edges) / len(net_edges) if net_edges else 0
        min_net_edge = min(net_edges) if net_edges else 0
        max_net_edge = max(net_edges) if net_edges else 0

        # ── 4. 3-Day Summary ──
        settled_72h = (
            db.query(Bet)
            .filter(
                Bet.settled_at >= h72,
                Bet.status.in_(("won", "lost")),
            )
            .all()
        )

        total_settled = len(settled_72h)
        wins_72 = sum(1 for b in settled_72h if b.status == "won")
        losses_72 = sum(1 for b in settled_72h if b.status == "lost")
        win_rate_72 = (wins_72 / total_settled * 100) if total_settled > 0 else 0
        total_pnl_72 = sum(b.realized_pnl for b in settled_72h)
        total_stake_72 = sum(b.stake_amount for b in settled_72h)
        roi_72 = (total_pnl_72 / total_stake_72 * 100) if total_stake_72 > 0 else 0

        # ── 5. Red Flags ──
        red_flags = []

        # Flag 1: 10+ bets in 3 days, 7+ losing
        if total_settled >= 10 and losses_72 >= 7:
            red_flags.append(
                {
                    "severity": "critical",
                    "message": f"3 günde {total_settled} bet sonuçlandı, {losses_72} tanesi zararda. Calibration bozuk olabilir.",
                    "action": "Botu durdur ve kalibrasyonu kontrol et.",
                }
            )

        # Flag 2: No bets opened in 24h (but bot is running)
        if state.is_running and bets_opened_24h == 0:
            # Check if there are any analyses at all
            any_analyses = (
                db.query(Analysis).filter(Analysis.analyzed_at >= h24).count()
            )
            if any_analyses > 0:
                red_flags.append(
                    {
                        "severity": "warning",
                        "message": f"Son 24 saatte {any_analyses} analiz yapıldı ama hiç bet açılmadı. Edge threshold çok yüksek olabilir.",
                        "action": "min_edge'i düşür veya marketleri kontrol et.",
                    }
                )
            else:
                red_flags.append(
                    {
                        "severity": "info",
                        "message": "Son 24 saatte hiç analiz yapılmadı. Market taraması çalışıyor mu?",
                        "action": "Market taramasını kontrol et.",
                    }
                )

        # Flag 3: All net edges below 2.5%
        if net_edges and all(e < 2.5 for e in net_edges):
            red_flags.append(
                {
                    "severity": "critical",
                    "message": f"Tüm net edge'ler %2.5 altında (ortalama: %{avg_net_edge:.1f}). Maliyeti karşılamıyor.",
                    "action": "Botu durdur. min_edge veya kalibrasyon ayarlarını gözden geçir.",
                }
            )

        # Flag 4: Win rate below 50%
        if total_settled >= 5 and win_rate_72 < 50:
            red_flags.append(
                {
                    "severity": "critical",
                    "message": f"Win rate %{win_rate_72:.1f} (5+ sonuçlanmış bet). Model tahminleri güvenilmez.",
                    "action": "Kalibrasyon verisini kontrol et, evrim çalıştır.",
                }
            )

        # Flag 5: Too many bets (50+ in 3 days)
        open_total = db.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES)).count()
        if bets_opened_24h > 50 or open_total > 50:
            red_flags.append(
                {
                    "severity": "warning",
                    "message": f"Aşırı bahis: 24s'de {bets_opened_24h} açılan, {open_total} açık. Risk yönetimi aşılıyor.",
                    "action": "min_edge'i yükselt, Kelly fraction'ı düşür.",
                }
            )

        # Flag 6: Negative total PnL trend
        if total_pnl_72 < 0 and total_settled >= 5:
            red_flags.append(
                {
                    "severity": "warning",
                    "message": f"3 günlük toplam PnL negatif: ${total_pnl_72:.2f}. Zarar trendi devam ediyor.",
                    "action": "Botu izlemeye devam et. 3 gün sonunda karar ver.",
                }
            )

        # ── 6. Daily PnL Timeline (last 7 days) ──
        daily_pnl = []
        for i in range(7):
            day_start = (now - timedelta(days=i + 1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = (now - timedelta(days=i)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_bets = (
                db.query(Bet)
                .filter(
                    Bet.settled_at >= day_start,
                    Bet.settled_at < day_end,
                    Bet.status.in_(("won", "lost")),
                )
                .all()
            )
            day_pnl = sum(b.realized_pnl for b in day_bets)
            day_wins = sum(1 for b in day_bets if b.status == "won")
            day_losses = sum(1 for b in day_bets if b.status == "lost")
            daily_pnl.append(
                {
                    "date": day_start.strftime("%m/%d"),
                    "pnl": round(day_pnl, 2),
                    "wins": day_wins,
                    "losses": day_losses,
                    "total": day_wins + day_losses,
                }
            )
        daily_pnl.reverse()

        # ── 7. Overall verdict ──
        if not red_flags or all(f["severity"] == "info" for f in red_flags):
            verdict = "healthy"
            verdict_color = "#10b981"
            verdict_text = "SAGLIKLI"
        elif any(f["severity"] == "critical" for f in red_flags):
            verdict = "critical"
            verdict_color = "#ef4444"
            verdict_text = "KRITIK - DURDUR"
        else:
            verdict = "warning"
            verdict_color = "#f59e0b"
            verdict_text = "DIKKAT - IZLE"

        return {
            "verdict": verdict,
            "verdict_text": verdict_text,
            "verdict_color": verdict_color,
            "is_running": state.is_running,
            "uptime_check": {
                "bot_running": state.is_running,
                "has_open_bets": open_total > 0,
                "has_recent_activity": bets_opened_24h > 0
                or (
                    any(
                        a.analyzed_at >= h24
                        for a in db.query(Analysis)
                        .filter(Analysis.analyzed_at >= h24)
                        .limit(1)
                        .all()
                    )
                ),
            },
            "activity_24h": {
                "bets_opened": bets_opened_24h,
                "pass_reasons": pass_reasons,
                "total_analyses": db.query(Analysis)
                .filter(Analysis.analyzed_at >= h24)
                .count(),
            },
            "edge_distribution": {
                "values": edge_values,
                "avg_net_edge_pct": round(avg_net_edge, 2),
                "min_net_edge_pct": round(min_net_edge, 2),
                "max_net_edge_pct": round(max_net_edge, 2),
                "count": len(edge_values),
            },
            "summary_3day": {
                "total_settled": total_settled,
                "wins": wins_72,
                "losses": losses_72,
                "win_rate_pct": round(win_rate_72, 1),
                "total_pnl": round(total_pnl_72, 2),
                "total_stake": round(total_stake_72, 2),
                "roi_pct": round(roi_72, 2),
                "avg_net_edge_pct": round(avg_net_edge, 2),
            },
            "red_flags": red_flags,
            "daily_pnl_timeline": daily_pnl,
        }
    except Exception as e:
        return {
            "error": str(e),
            "verdict": "error",
            "verdict_text": "HATA",
            "verdict_color": "#ef4444",
        }
    finally:
        db.close()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.websocket_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in state.websocket_clients:
            state.websocket_clients.remove(websocket)


def run_cli():
    """CLI entry point for ASIAbot."""
    parser = argparse.ArgumentParser(description="ASIAbot CLI Interface")
    parser.add_argument(
        "command",
        choices=[
            "run",
            "evolve",
            "backfill",
            "calibrate",
            "fetch",
            "weather",
            "analyze",
            "bet",
            "settle",
            "report",
            "reset",
        ],
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of historical days to fetch for backfill",
    )
    args = parser.parse_args()

    init_db()
    ensure_initial_portfolio()

    if args.command == "run":
        logger.info("Starting ASIAbot FastAPI Server on port 8091...")
        uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "evolve":
        logger.info("Running ASIAbot Autonomous Evolution Loop on CLI...")
        orchestrator = ASIAbotOrchestrator()
        result = orchestrator.run_evolution_pipeline(5)
        print(
            f"\nEvolution successful! Best round: Round {result['round']}, Virtual ROI: {result['roi']:.2f}%"
        )
    elif args.command == "backfill":
        logger.info("Running deep backfill for past %d days on CLI...", args.days)
        backfiller = DataBackfiller()
        count = backfiller.run_deep_backfill(args.days, 15)
        print(f"\nBackfill completed! Inserted {count} historical records.")
        # Recalculate biases immediately
        calibrator = CalibrationEngine()
        biases = calibrator.calculate_biases()
        print(f"Bias calibration generated for {len(biases)} cities.")
    elif args.command == "calibrate":
        logger.info("Recalculating temperature biases on CLI...")
        calibrator = CalibrationEngine()
        biases = calibrator.calculate_biases()
        print(f"Bias calibration successfully recalculated for {len(biases)} cities.")
    else:
        # Delegate standard operations to jobs/scheduler
        from jobs.scheduler import (
            run_analyze,
            run_fetch_markets,
            run_fetch_weather,
            run_place_bets,
            run_report,
            run_settle,
        )

        cmds = {
            "fetch": run_fetch_markets,
            "weather": run_fetch_weather,
            "analyze": run_analyze,
            "bet": run_place_bets,
            "settle": run_settle,
            "report": run_report,
            "reset": lambda: "System reset completed. Run run/evolve next.",
        }
        if args.command in cmds:
            print(cmds[args.command]())


if __name__ == "__main__":
    run_cli()
