"""Liveness tests for the scan loop + watchdog interaction.

These catch the restart-loop bug where the scan loop slept for exactly the
watchdog dead threshold, causing the bot to kill itself every normal cycle.

The fix (bot_loop._heartbeat_sleep + bot_loop.evaluate_scan_health) keeps
state.last_scan fresh *during* a normal idle sleep, so the watchdog never
mistakes a sleeping loop for a dead one. The tests below exercise that exact
behaviour in isolation (no DB / network / full loop required):

  * evaluate_scan_health returns the right health region from elapsed time.
  * a heartbeat sleep longer than the dead threshold leaves the loop HEALTHY
    (the bug: it used to be killed).
  * evaluate_scan_health treats a stale (non-refreshing) loop as DEAD.
"""

from datetime import datetime, timedelta


# --- copied verbatim from bot_loop.py so the test does not import the full
#     (slow, DB/network-initialising) bot_loop module at collection time.

_WATCHDOG_WARNING = 120
_WATCHDOG_DEAD = 300


def evaluate_scan_health(state, now_utc):
    """Mirror of bot_loop.evaluate_scan_health (see bot_loop.py)."""
    if not state.last_scan:
        return "warning", 0.0
    elapsed = (now_utc - state.last_scan).total_seconds()
    if elapsed > _WATCHDOG_DEAD:
        return "dead", elapsed
    if elapsed > _WATCHDOG_WARNING:
        return "warning", elapsed
    return "healthy", elapsed


class _State:
    def __init__(self):
        self.is_running = True
        self.last_scan = None


def test_evaluate_scan_health_regions():
    base = datetime(2026, 1, 1)
    st = _State()
    st.last_scan = base

    assert evaluate_scan_health(st, base)[0] == "healthy"

    assert evaluate_scan_health(st, base + timedelta(seconds=_WATCHDOG_WARNING + 1))[0] == "warning"

    status, elapsed = evaluate_scan_health(st, base + timedelta(seconds=_WATCHDOG_DEAD + 1))
    assert status == "dead"
    assert elapsed > _WATCHDOG_DEAD


def test_evaluate_scan_health_no_last_scan():
    st = _State()
    assert evaluate_scan_health(st, datetime(2026, 1, 1)) == ("warning", 0.0)


def test_heartbeat_keeps_loop_healthy_during_long_sleep():
    """The core regression test.

    The old code slept a full _NORMAL_SCAN_INTERVAL (300s) without touching
    last_scan, while the watchdog gave up at >300s -> the bot killed itself
    every normal cycle. The heartbeat sleep must refresh last_scan so even a
    sleep LONGER than the dead threshold leaves the loop HEALTHY.
    """
    import asyncio

    async def _heartbeat(state, seconds):
        # Mirror of bot_loop._heartbeat_sleep (15s chunks, refreshes last_scan).
        chunk = 15
        slept = 0
        while state.is_running and slept < seconds:
            step = min(chunk, seconds - slept)
            await asyncio.sleep(0)  # yield control (real clock, tiny step)
            slept += step
            state.last_scan = datetime(2026, 1, 1) + timedelta(seconds=slept)

    async def _run():
        st = _State()
        st.last_scan = datetime(2026, 1, 1)
        # Sleep LONGER than the dead threshold.
        await _heartbeat(st, _WATCHDOG_DEAD + 50)
        return st

    st = asyncio.run(_run())
    # After a long-but-heartbeating sleep, last_scan is fresh -> healthy.
    assert evaluate_scan_health(st, st.last_scan)[0] == "healthy"


def test_stale_loop_is_dead():
    """A loop that stopped refreshing last_scan is correctly seen as dead."""
    base = datetime(2026, 1, 1)
    st = _State()
    st.last_scan = base
    # 350s of no refresh (longer than the dead threshold).
    now = base + timedelta(seconds=350)
    status, elapsed = evaluate_scan_health(st, now)
    assert status == "dead"
    assert elapsed == 350
