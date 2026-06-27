"""Analyze Trailing Stop performance — fixed for no exit_price."""

from database.db import get_db_session
from database.models import Bet
from sqlalchemy import func

db = get_db_session()

# TS entry/exit prices
avg_entry = (
    db.query(func.avg(Bet.entry_price))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)
avg_current = (
    db.query(func.avg(Bet.current_price))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)
avg_pnl = (
    db.query(func.avg(Bet.pnl)).filter(Bet.close_reason.like("trailing_stop%")).scalar()
    or 0
)
avg_bet = (
    db.query(func.avg(Bet.stake_amount))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)

print("=== TS ENTRY/EXIT PRICES ===")
print(f"  Avg entry price: {avg_entry:.3f}")
print(f"  Avg current_price (at close): {avg_current:.3f}")
print(f"  Avg PnL per bet: ${avg_pnl:.2f}")
print(f"  Avg bet size: ${avg_bet:.2f}")

# YES vs NO side
yes_ts = (
    db.query(Bet)
    .filter(Bet.close_reason.like("trailing_stop%"), Bet.entry_price > 0.50)
    .count()
)
no_ts = (
    db.query(Bet)
    .filter(Bet.close_reason.like("trailing_stop%"), Bet.entry_price <= 0.50)
    .count()
)
print(f"\n  YES side (entry > 0.50): {yes_ts}")
print(f"  NO side (entry <= 0.50): {no_ts}")

# TS losses — were they winning before triggering TS?
# entry vs current: if current > entry for NO bets, they were profitable
ts_losses = (
    db.query(Bet).filter(Bet.close_reason.like("trailing_stop%"), Bet.pnl < 0).all()
)

was_profitable = 0
was_not = 0
for b in ts_losses:
    if b.side and b.side.upper() == "NO":
        # NO bet: profitable when current > entry (price went up = YES probability up = NO position gains)
        # Wait, NO bet profits when price drops. entry=0.40, current=0.30 means profit.
        if b.current_price < b.entry_price:
            was_profitable += 1  # Was profitable, TS didn't trigger in time
        else:
            was_not += 1
    else:
        # YES bet: profitable when current > entry
        if b.current_price > b.entry_price:
            was_profitable += 1
        else:
            was_not += 1

print("\n=== TS LOSSES — Were they profitable before trigger? ===")
print(f"  Were profitable (current on favorable side): {was_profitable}")
print(f"  Were NOT profitable: {was_not}")

# Average entry price for TS losses
avg_entry_loss = (
    db.query(func.avg(Bet.entry_price))
    .filter(Bet.close_reason.like("trailing_stop%"), Bet.pnl < 0)
    .scalar()
    or 0
)
avg_entry_win = (
    db.query(func.avg(Bet.entry_price))
    .filter(Bet.close_reason.like("trailing_stop%"), Bet.pnl > 0)
    .scalar()
    or 0
)
print(f"\n  Avg entry (losses): {avg_entry_loss:.3f}")
print(f"  Avg entry (wins): {avg_entry_win:.3f}")

# top 5 biggest TS losses
print("\n=== TOP 5 TS LOSSES ===")
top_losses = (
    db.query(Bet)
    .filter(Bet.close_reason.like("trailing_stop%"), Bet.pnl < 0)
    .order_by(Bet.pnl.asc())
    .limit(5)
    .all()
)
for b in top_losses:
    print(
        f"  ${b.stake_amount:.2f} @ {b.entry_price:.3f} -> current={b.current_price:.3f} pnl=${b.pnl:.2f} side={b.side}"
    )

db.close()
