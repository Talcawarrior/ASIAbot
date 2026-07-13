"""ASIAbot entry point — CLI and bot launcher.

Thin wrapper that imports the FastAPI app, BotState, and bot loops
from their dedicated modules:

  api.py      — FastAPI routes, BotState, app definition
  bot_loop.py — scan_and_bet_loop, settlement_loop
"""

import argparse
import asyncio
import os
import platform
import signal
import subprocess
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from config.logging_config import setup_logging
from config.settings import config
from database.db import ensure_initial_portfolio, get_db_session, init_db
from database.models import Analysis, Bet, Portfolio

setup_logging()

# Import app, state, and loop functions from split modules.
from api import app, scan_and_bet_loop, settlement_loop, state  # noqa: E402

logger = __import__("logging").getLogger(__name__)


async def karpathy_weekly_loop(state):
    """Layer 1: Karpathy weekly optimization (Sunday 03:00 UTC).

    MEDIUM FIX (double-trigger guard): previously this loop had no
    `last_run_week` tracking, so if the bot restarted during the 10-minute
    Sunday 03:00 UTC window, Karpathy would run twice in the same week —
    potentially overwriting good strategy params with a fresh (possibly
    worse) optimization. Now tracks the ISO week number to prevent this,
    mirroring the `last_run_date` pattern used by `asi_evolve_daily_loop`.
    """
    from asi_engine.karpathy_weekly import run_karpathy_weekly

    logger.info("KARPATHY WEEKLY: Loop started (will run Sunday 03:00 UTC)")
    last_run_week: int | None = None  # ISO week number, e.g. 28 for mid-July
    while state.is_running:
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            # Sunday=6, 03:00–03:10 UTC window, and not already run this ISO week.
            iso_year, iso_week, _ = now.isocalendar()
            current_week_key = iso_year * 100 + iso_week
            if (
                now.weekday() == 6
                and now.hour == 3
                and now.minute < 10
                and last_run_week != current_week_key
            ):
                logger.info("KARPATHY WEEKLY: Running weekly optimization")
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_karpathy_weekly, rounds=6, use_llm=False, seed=42),
                    timeout=3600,
                )
                logger.info(f"KARPATHY WEEKLY: Completed - {result}")
                last_run_week = current_week_key
            await asyncio.sleep(600)
        except TimeoutError:
            logger.error("KARPATHY WEEKLY: Timeout")
        except Exception as e:
            logger.error(f"KARPATHY WEEKLY: Error - {e}")
            await asyncio.sleep(600)


async def asi_evolve_daily_loop(state):
    """Layer 2: ASI-Evolve daily optimization (02:00 UTC daily)."""
    from asi_engine.asi_evolve import run_asi_evolve_daily

    logger.info("ASI-EVOLVE DAILY: Starting daily optimization")
    last_run_date = None
    while state.is_running:
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            if now.hour == 2 and now.minute < 10 and last_run_date != now.date():
                logger.info("ASI-EVOLVE DAILY: Running daily optimization")
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_asi_evolve_daily, generations=50, population_size=20),
                    timeout=1800,
                )
                logger.info(f"ASI-EVOLVE DAILY: Completed - {result}")
                last_run_date = now.date()
            await asyncio.sleep(600)
        except TimeoutError:
            logger.error("ASI-EVOLVE DAILY: Timeout")
        except Exception as e:
            logger.error(f"ASI-EVOLVE DAILY: Error - {e}")
            await asyncio.sleep(600)


# ── Port conflict prevention ───────────────────────────────────────────────
def _kill_port_owner(port: int, host: str = "127.0.0.1") -> bool:
    """Kill any process listening on *port* so we can bind to it.

    Works on Windows (netstat + taskkill), Linux (lsof + kill),
    and macOS (lsof + kill).  Returns True if a process was killed.
    """
    is_windows = platform.system() == "Windows"
    my_pid = os.getpid()

    try:
        if is_windows:
            raw = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pids = {
                int(line.split()[-1]) for line in raw.splitlines() if f":{port}" in line and "LISTENING" in line
            } - {my_pid}
            if not pids:
                return False
            for pid in pids:
                logger.warning("PORT CONFLICT: killing PID %d that owns port %d", pid, port)
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            for _ in range(10):
                time.sleep(0.5)
                check = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
                if not any(f":{port}" in line and "LISTENING" in line for line in check.splitlines()):
                    return True
            logger.error("Port %d still occupied after killing processes", port)
            return False
        else:
            raw = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL)
            pids = {int(line.strip()) for line in raw.splitlines() if line.strip()} - {my_pid}
            if not pids:
                return False
            for pid in pids:
                logger.warning("PORT CONFLICT: killing PID %d that owns port %d", pid, port)
                with suppress(OSError):
                    os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _ensure_port_free(port: int, host: str = "127.0.0.1") -> None:
    """Ensure *port* is free before starting uvicorn. Kill stale processes."""
    if _kill_port_owner(port, host):
        logger.info("Port %d cleared — stale process removed", port)


def run_cli():
    """CLI entry point: run, reset, fetch, parse, weather, analyze."""
    parser = argparse.ArgumentParser(
        description="ASIAbot — Polymarket weather trading bot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py bot       # Run bot + API + dashboard + background loops
  python main.py run       # API + dashboard only (no background loops)
  python main.py fetch     # One-shot: fetch markets from Polymarket
  python main.py analyze   # One-shot: analyze pending markets
  python main.py bet       # One-shot: place bets on analyzed markets
  python main.py settle    # One-shot: settle resolved markets
  python main.py report    # One-shot: print portfolio report
  python main.py reset     # Cancel all bets, reset portfolio (DESTRUCTIVE)
""",
    )
    parser.add_argument(
        "command",
        choices=[
            "bot",
            "run",
            "reset",
            "fetch",
            "parse",
            "weather",
            "analyze",
            "bet",
            "settle",
            "report",
        ],
        help="Command to run. Use --help for details.",
    )
    args = parser.parse_args()
    init_db()
    ensure_initial_portfolio()
    from jobs.scheduler import (
        run_analyze,
        run_fetch_markets,
        run_fetch_weather,
        run_parse_markets,
        run_place_bets,
        run_report,
        run_settle,
    )

    cmds = {
        "fetch": run_fetch_markets,
        "parse": run_parse_markets,
        "weather": run_fetch_weather,
        "analyze": run_analyze,
        "bet": run_place_bets,
        "settle": run_settle,
        "report": run_report,
    }
    if args.command == "bot":
        # ── Auto-build dashboard if source is newer than build ──────────────
        _base = os.path.dirname(os.path.abspath(__file__))
        _out = os.path.join(_base, "out")
        _src = os.path.join(_base, "src")
        _pkg = os.path.join(_base, "package.json")

        def _needs_build() -> bool:
            """Check if src/ is newer than out/ or out/ doesn't exist."""
            if not os.path.isdir(_out):
                return True
            if not os.path.isfile(_pkg):
                return False
            out_mtime = os.path.getmtime(_out)
            pkg_mtime = os.path.getmtime(_pkg)
            # Check src/ modification time
            src_mtime = 0.0
            for root, _dirs, files in os.walk(_src):
                for f in files:
                    src_mtime = max(src_mtime, os.path.getmtime(os.path.join(root, f)))
            return max(pkg_mtime, src_mtime) > out_mtime

        if _needs_build() and os.path.isfile(_pkg):
            # HIZ OPTIMIZASYONU: SKIP_DASHBOARD_BUILD=true ise build'i tamamen atla.
            # Production'da out/ commit'liyse veya CI'da build yapildiysa kullan.
            # Bot aninda acilir (npm install + next build atlanir).
            if os.getenv("SKIP_DASHBOARD_BUILD", "false").lower() == "true":
                logger.info("SKIP_DASHBOARD_BUILD=true — dashboard build atlandi")
            else:
                # FIX: node_modules yoksa once npm install calistir.
                # HIZ: npm ci kullan (package-lock varsa 2-3x daha hizli).
                _node_modules = os.path.join(_base, "node_modules")
                _lock = os.path.join(_base, "package-lock.json")
                if not os.path.isdir(_node_modules):
                    install_cmd = ["npm", "ci"] if os.path.isfile(_lock) else ["npm", "install"]
                    logger.info("node_modules not found — running '%s' first...", " ".join(install_cmd))
                    try:
                        install_result = subprocess.run(
                            install_cmd,
                            cwd=_base,
                            capture_output=True,
                            text=True,
                            timeout=300,
                        )
                        if install_result.returncode == 0:
                            logger.info("%s SUCCESS", " ".join(install_cmd))
                        else:
                            logger.warning("%s failed: %s", " ".join(install_cmd), install_result.stderr[:500])
                    except Exception as e:
                        logger.warning("npm install error: %s", e)

                logger.info("Dashboard source changed — auto-building...")
                try:
                    result = subprocess.run(
                        ["npx", "next", "build"],
                        cwd=_base,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode == 0:
                        logger.info("Dashboard auto-build SUCCESS")
                    else:
                        logger.warning("Dashboard auto-build failed: %s", result.stderr[:500])
                except Exception as e:
                    logger.warning("Dashboard auto-build error: %s", e)

        # ── Start bot: API + Dashboard + Background loops ────────────────────
        if os.path.isdir(_out):
            from fastapi.staticfiles import StaticFiles

            app.mount(
                "/_next",
                StaticFiles(directory=os.path.join(_out, "_next")),
                name="next-static",
            )
            app.mount("/", StaticFiles(directory=_out, html=True), name="dashboard")

        # Start background loops on FastAPI startup (lifespan handler).
        # CRITICAL FIX (lifespan silent override): previously this replaced
        # api.py's `lifespan` via `app.router.lifespan_context = bot_lifespan`,
        # which silently discarded any future changes made in api.py. We now
        # explicitly replicate ALL startup steps from api.py.lifespan here
        # (init_db, state.initialize_modules, ensure_initial_portfolio) AND
        # add the bot-specific loops + warm-start. We also properly await
        # task cancellation on shutdown (matching api.py's graceful pattern).
        @asynccontextmanager
        async def bot_lifespan(app):
            logger.info("LIFESPAN STARTUP - Starting bot loops (bot mode)")
            # ── Mirror api.py lifespan startup ──────────────────────────────
            init_db()
            state.initialize_modules()
            try:
                ensure_initial_portfolio()
            except Exception as e:
                logger.warning("Portfolio init warning: %s", e)

            # ── Bot-mode-only: WeatherEngine warm-start ─────────────────────
            # PER-5 FIX: Warm-start WeatherEngine in-process cache from DB.
            # Loads last 3 days of ensemble forecasts so first scan is fast.
            try:
                from engine.calculator import WeatherEngine

                we = WeatherEngine(db_session_factory=get_db_session)
                loaded = we.warm_start_from_db()
                if loaded > 0:
                    logger.info("WeatherEngine warm-start: %d cities loaded from DB", loaded)
            except Exception as e:
                logger.warning("WeatherEngine warm-start failed: %s", e)

            # ── Bot-mode-only: Start background loops ───────────────────────
            state.is_running = True
            state.locked = False
            state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop(state))
            state.tasks["settlement"] = asyncio.create_task(settlement_loop(state))
            state.tasks["karpathy_weekly"] = asyncio.create_task(karpathy_weekly_loop(state))
            state.tasks["asi_evolve_daily"] = asyncio.create_task(asi_evolve_daily_loop(state))
            logger.info("Bot loops started (scan_and_bet + settlement + karpathy_weekly + asi_evolve_daily)")
            yield
            # ── Shutdown: cancel + AWAIT (graceful, matches api.py) ────────
            logger.info("LIFESPAN SHUTDOWN - Stopping bot loops")
            for t in list(state.tasks.values()):
                if not t.done():
                    t.cancel()
            # Await cancelled tasks so pending work / final DB writes complete
            # before the process exits. Without this, in-flight bets could be
            # left half-written to the DB.
            await asyncio.gather(*state.tasks.values(), return_exceptions=True)
            state.tasks.clear()
            state.is_running = False

        app.router.lifespan_context = bot_lifespan

        import uvicorn  # noqa: I001

        _ensure_port_free(config.PORT, config.HOST)
        uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "run":
        # ── Mount Next.js static dashboard (must be LAST — catch-all) ──────
        _base = os.path.dirname(os.path.abspath(__file__))
        _out = os.path.join(_base, "out")
        if os.path.isdir(_out):
            from fastapi.staticfiles import StaticFiles

            app.mount(
                "/_next",
                StaticFiles(directory=os.path.join(_out, "_next")),
                name="next-static",
            )
            app.mount("/", StaticFiles(directory=_out, html=True), name="dashboard")

        import uvicorn  # noqa: I001

        _ensure_port_free(config.PORT, config.HOST)
        uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "reset":
        db = get_db_session()
        try:
            # HIGH FIX: previously `db.query(Bet).update({"status": "cancelled"})`
            # blanket-cancelled EVERY bet — including settled "won" / "lost"
            # bets — destroying historical PnL data. Now only OPEN bets are
            # cancelled, so historical settled bets (and their PnL) are
            # preserved for backtesting / SIA optimization.
            open_statuses = ("pending", "placed", "open")
            cancelled_count = (
                db.query(Bet).filter(Bet.status.in_(open_statuses)).update({"status": "cancelled"})
            )
            db.query(Analysis).delete()
            pf = db.query(Portfolio).filter(Portfolio.id == 1).first()
            if pf is None:
                # No portfolio row yet — create fresh.
                pf = Portfolio(id=1, cash_balance=config.INITIAL_PORTFOLIO)
                db.add(pf)
            else:
                # FIX: Reset ALL portfolio fields, not just cash_balance.
                # Previously total_won / total_lost / total_realized_pnl /
                # total_value / current_value / daily_pnl were left stale.
                pf.cash_balance = config.INITIAL_PORTFOLIO
                pf.total_value = config.INITIAL_PORTFOLIO
                pf.current_value = config.INITIAL_PORTFOLIO
                pf.initial_value = config.INITIAL_PORTFOLIO
                pf.total_realized_pnl = 0.0
                pf.total_won = 0
                pf.total_lost = 0
                pf.daily_pnl = 0.0
            db.commit()
            logger.info(
                "Reset complete: %d open bets cancelled, analyses cleared. "
                "Settled bets (won/lost) preserved for history.",
                cancelled_count,
            )
        finally:
            db.close()
    elif args.command in cmds:
        print(cmds[args.command]())


if __name__ == "__main__":
    run_cli()
