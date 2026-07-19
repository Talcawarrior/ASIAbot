"""Daily self-evolution job: refresh the Brier datastore + run the 3-tier loop.

This wires the previously-orphaned evolution system into the always-on bot.
The live trading loop continuously fills the SQLite DB; this job converts that
data into the unified Brier datastore and then runs the LLM loop orchestrator
(karpathy_weekly + asi_evolve_daily + sia_hourly), which deploys the best
strategy params / model weights when (and only when) they pass the gates.

Runs at most once per UTC day. A persisted marker file makes this robust to
the bot's frequent restarts (an in-memory flag would re-run on every restart).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger("EVOLUTION_JOB")

# Only run at/after this UTC hour (aligns with the "suggested cron 03:00").
EVOLUTION_UTC_HOUR = 3

_MARKER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    ".last_evolution_run",
)


def _read_marker() -> str | None:
    try:
        with open(_MARKER_PATH, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _write_marker(day: str) -> None:
    try:
        os.makedirs(os.path.dirname(_MARKER_PATH), exist_ok=True)
        with open(_MARKER_PATH, "w", encoding="utf-8") as fh:
            fh.write(day)
    except OSError as exc:
        logger.warning("Could not write evolution marker: %s", exc)


def should_run(now: datetime | None = None) -> bool:
    """True iff we haven't run yet today and it's past EVOLUTION_UTC_HOUR."""
    now = now or datetime.now(UTC)
    if now.hour < EVOLUTION_UTC_HOUR:
        return False
    return _read_marker() != now.strftime("%Y-%m-%d")


def run_evolution_cycle(now: datetime | None = None) -> dict:
    """Backfill the Brier datastore from the live DB, then run the 3-tier loop.

    Marks today as done even on failure to avoid restart-storm retries; the
    next attempt is the following day.
    """
    now = now or datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    result: dict = {"day": today}
    try:
        from data_pipeline.backfill_from_live_db import backfill

        logger.info("Daily evolution: backfilling Brier datastore from live DB")
        result["backfill"] = backfill()

        from asi_engine.llm_loop_orchestrator import run_full_cycle

        logger.info("Daily evolution: running 3-tier orchestrator (use_llm=False)")
        summary = run_full_cycle(use_llm=False)
        result["deployed"] = summary.get("final_deploy", {}).get("deployed")
        result["deploy_reason"] = summary.get("final_deploy", {}).get("reason")
        logger.info(
            "Daily evolution complete: deployed=%s reason=%s",
            result.get("deployed"),
            result.get("deploy_reason"),
        )
    except Exception as exc:  # noqa: BLE001 - loop must never die
        logger.error("Daily evolution failed: %s", exc, exc_info=True)
        result["error"] = str(exc)
    finally:
        _write_marker(today)
    return result
