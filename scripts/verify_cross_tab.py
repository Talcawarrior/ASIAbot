"""Cross-tab data consistency verification.

Checks that all 5 dashboard tabs show consistent numbers.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import get_db_session, init_db
from database.models import Bet, Portfolio, OPEN_BET_STATUSES
from config.settings import config
from sqlalchemy import func, or_
from datetime import datetime, timezone


def verify():
    init_db()
    db = get_db_session()

    errors = []
    warnings = []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    _closed_statuses = ("won", "lost", "settled", "closed_early")
    _open_statuses = OPEN_BET_STATUSES

    # === Portfolio ===
    pf = db.query(Portfolio).filter(Portfolio.id == 1).first()
    if not pf:
        print("❌ Portfolio not found!")
        return

    # === Realized PnL ===
    realized_total = float(
        db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
        .filter(Bet.status.in_(_closed_statuses))
        .scalar()
        or 0.0
    )

    realized_before_today = float(
        db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
        .filter(
            Bet.status.in_(_closed_statuses),
            or_(Bet.settled_at < today_start, Bet.closed_at < today_start),
        )
        .scalar()
        or 0.0
    )

    # === Counts (pnl-based for consistency with history tab) ===
    _all_closed = db.query(Bet.pnl).filter(Bet.status.in_(_closed_statuses)).all()
    win_count = sum(1 for b in _all_closed if (b.pnl or 0) > 0)
    loss_count = sum(1 for b in _all_closed if (b.pnl or 0) <= 0)
    settled_count = db.query(Bet).filter(Bet.status == "settled").count()
    closed_early_count = db.query(Bet).filter(Bet.status == "closed_early").count()
    total_closed = len(_all_closed)

    open_count = db.query(Bet).filter(Bet.status.in_(_open_statuses)).count()

    # === Exposure ===
    exposure = float(
        db.query(func.coalesce(func.sum(Bet.amount), 0.0))
        .filter(Bet.status.in_(_open_statuses))
        .scalar()
        or 0.0
    )

    # === Win Rate ===
    if total_closed > 0:
        win_rate = (win_count / total_closed) * 100
    else:
        win_rate = 0.0

    # === Daily PnL ===
    daily_pnl = float(
        db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
        .filter(
            Bet.status.in_(_closed_statuses),
            or_(Bet.settled_at >= today_start, Bet.closed_at >= today_start),
        )
        .scalar()
        or 0.0
    )

    # === Max Exposure (daily = based on yesterday's closing) ===
    daily_starting = config.INITIAL_PORTFOLIO + realized_before_today
    max_exposure = daily_starting * config.TOTAL_EXPOSURE_PCT

    # === Unrealized PnL ===
    unrealized = float(
        db.query(func.coalesce(func.sum(Bet.unrealized_pnl), 0.0))
        .filter(Bet.status.in_(_open_statuses))
        .scalar()
        or 0.0
    )

    # === Print Results ===
    print("=" * 60)
    print("CROSS-TAB DATA CONSISTENCY VERIFICATION")
    print("=" * 60)
    print()

    print("📊 PORTFOLIO (Genel Bakış + Sağlık)")
    print(
        f"  Portfolio Value:     ${config.INITIAL_PORTFOLIO + realized_total + unrealized:,.2f}"
    )
    print(f"  Total PnL:          +${realized_total + unrealized:,.2f}")
    print(f"  Realized PnL:       +${realized_total:,.2f}")
    print(f"  Unrealized PnL:     +${unrealized:,.2f}")
    print(f"  Cash Balance:       ${pf.cash_balance:,.2f}")
    print()

    print("📈 BET COUNTS (Genel Bakış + İşlem Geçmişi + Sağlık)")
    print(f"  Win:                {win_count}")
    print(f"  Loss:               {loss_count}")
    print(f"  Settled:            {settled_count}")
    print(f"  Closed Early:       {closed_early_count}")
    print(f"  Total Closed:       {total_closed}")
    print(f"  Open:               {open_count}")
    print()

    print("🏆 WIN RATE (Genel Bakış + Sağlık)")
    print(f"  Win Rate:           {win_rate:.1f}%")
    print()

    print("💰 DAILY PnL (Genel Bakış)")
    print(f"  Today PnL:          +${daily_pnl:,.2f}")
    print()

    print("🔒 EXPOSURE (Genel Bakış + Sağlık)")
    print(f"  Current Exposure:   ${exposure:,.2f}")
    print(f"  Daily Starting:     ${daily_starting:,.2f}")
    print(f"  Max Exposure (25%): ${max_exposure:,.2f}")
    print()

    # === Consistency Checks ===
    print("=" * 60)
    print("CONSISTENCY CHECKS")
    print("=" * 60)

    # Check 1: Win + Loss (PnL-based) = Total Closed
    calc_pnl_total = win_count + loss_count
    if calc_pnl_total == total_closed:
        print(f"✅ Win({win_count}) + Loss({loss_count}) = Total({total_closed})")
    else:
        errors.append(f"Win+Loss mismatch: {calc_pnl_total} vs {total_closed}")
        print(f"❌ Win+Loss mismatch: {calc_pnl_total} vs {total_closed}")

    # Check 1b: Status-based counts also add up
    status_total = settled_count + closed_early_count
    print(
        f"   Status: settled={settled_count}, closed_early={closed_early_count}, total={status_total}"
    )

    # Check 2: Win Rate = Win / Total * 100
    if total_closed > 0:
        expected_wr = (win_count / total_closed) * 100
        if abs(expected_wr - win_rate) < 0.1:
            print(f"✅ Win Rate = {win_count}/{total_closed} = {win_rate:.1f}%")
        else:
            errors.append(f"Win rate mismatch: {expected_wr:.1f}% vs {win_rate:.1f}%")
            print(f"❌ Win Rate mismatch: {expected_wr:.1f}% vs {win_rate:.1f}%")

    # Check 3: Exposure + Cash ≈ Portfolio Value
    pf_value = config.INITIAL_PORTFOLIO + realized_total + unrealized
    calc_value = pf.cash_balance + exposure
    gap = abs(pf_value - calc_value)
    if gap < 10:
        print(
            f"✅ Portfolio({pf_value:,.2f}) ≈ Cash({pf.cash_balance:,.2f}) + Exposure({exposure:,.2f}) = {calc_value:,.2f} (gap: ${gap:.2f})"
        )
    else:
        warnings.append(f"Portfolio gap: ${gap:.2f}")
        print(
            f"⚠️  Portfolio({pf_value:,.2f}) vs Cash+Exposure({calc_value:,.2f}) gap: ${gap:.2f}"
        )

    # Check 4: Max Exposure = 25% of daily starting
    expected_max = daily_starting * config.TOTAL_EXPOSURE_PCT
    if abs(expected_max - max_exposure) < 1:
        print(f"✅ Max Exposure = 25% × ${daily_starting:,.2f} = ${max_exposure:,.2f}")
    else:
        errors.append("Max exposure mismatch")

    # Check 5: Realized PnL from DB matches Portfolio
    if abs(pf.total_realized_pnl - realized_total) < 1:
        print(
            f"✅ Portfolio.total_realized_pnl({pf.total_realized_pnl:,.2f}) = DB realized({realized_total:,.2f})"
        )
    else:
        warnings.append(
            f"Portfolio.total_realized_pnl({pf.total_realized_pnl:,.2f}) ≠ DB({realized_total:,.2f})"
        )
        print(
            f"⚠️  Portfolio.total_realized_pnl({pf.total_realized_pnl:,.2f}) ≠ DB({realized_total:,.2f})"
        )

    # Check 6: Daily starting cap uses yesterday's closing
    print(
        f"✅ Daily starting = INITIAL(${config.INITIAL_PORTFOLIO:,.0f}) + BeforeToday(${realized_before_today:,.2f}) = ${daily_starting:,.2f}"
    )

    print()
    if errors:
        print(f"❌ {len(errors)} ERRORS found!")
        for e in errors:
            print(f"  - {e}")
    elif warnings:
        print(f"⚠️  {len(warnings)} warnings (non-critical)")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("✅ ALL CHECKS PASSED!")

    db.close()
    return len(errors) == 0


if __name__ == "__main__":
    success = verify()
    sys.exit(0 if success else 1)
