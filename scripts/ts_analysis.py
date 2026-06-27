"""Analyze Trailing Stop performance vs other exit types."""

from database.db import get_db_session
from database.models import Bet
from sqlalchemy import func

db = get_db_session()

for name, prefix in [
    ("TRAILING STOP", "trailing_stop"),
    ("TAKE PROFIT", "take_profit"),
    ("STOP LOSS", "stop_loss"),
    ("TIME DECAY", "time_decay"),
]:
    wins = (
        db.query(Bet).filter(Bet.close_reason.like(f"{prefix}%"), Bet.pnl > 0).count()
    )
    losses = (
        db.query(Bet).filter(Bet.close_reason.like(f"{prefix}%"), Bet.pnl < 0).count()
    )
    total_pnl = (
        db.query(func.sum(Bet.pnl)).filter(Bet.close_reason.like(f"{prefix}%")).scalar()
        or 0
    )
    avg_loss = (
        db.query(func.avg(Bet.pnl))
        .filter(Bet.close_reason.like(f"{prefix}%"), Bet.pnl < 0)
        .scalar()
        or 0
    )
    avg_win = (
        db.query(func.avg(Bet.pnl))
        .filter(Bet.close_reason.like(f"{prefix}%"), Bet.pnl > 0)
        .scalar()
        or 0
    )
    total = wins + losses
    wr = wins / total * 100 if total > 0 else 0
    print(f"\n=== {name} ===")
    print(f"  Wins: {wins}, Losses: {losses} (total {total})")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Total PnL: ${total_pnl:.2f}")
    print(f"  Avg win: ${avg_win:.2f}, Avg loss: ${avg_loss:.2f}")

# TS loss distribution
print("\n=== TS LOSS SIZE DISTRIBUTION ===")
ts_losses = (
    db.query(Bet).filter(Bet.close_reason.like("trailing_stop%"), Bet.pnl < 0).all()
)
bins = {"0 to -1": 0, "-1 to -5": 0, "-5 to -10": 0, "-10 to -50": 0, "-50+": 0}
for b in ts_losses:
    p = b.pnl
    if p >= -1:
        bins["0 to -1"] += 1
    elif p >= -5:
        bins["-1 to -5"] += 1
    elif p >= -10:
        bins["-5 to -10"] += 1
    elif p >= -50:
        bins["-10 to -50"] += 1
    else:
        bins["-50+"] += 1
for k, v in bins.items():
    print(f"  {k}: {v}")

# Entry price analysis for TS
print("\n=== TS ENTRY/EXIT PRICES ===")
avg_entry = (
    db.query(func.avg(Bet.entry_price))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)
avg_exit = (
    db.query(func.avg(Bet.exit_price))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)
avg_edge = (
    db.query(func.avg(Bet.edge_at_entry))
    .filter(Bet.close_reason.like("trailing_stop%"))
    .scalar()
    or 0
)
print(f"  Avg entry price: {avg_entry:.3f}")
print(f"  Avg exit price: {avg_exit:.3f}")
print(f"  Avg edge at entry: {avg_edge:.3f}")

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
print(f"  YES side (entry > 0.50): {yes_ts}")
print(f"  NO side (entry <= 0.50): {no_ts}")

# TS loss by bet size
print("\n=== TS LOSS BY BET SIZE ===")
for b in ts_losses[:5]:
    print(
        f"  ${b.bet_amount:.2f} @ entry={b.entry_price:.3f} exit={b.exit_price:.3f} pnl=${b.pnl:.2f} reason={b.close_reason}"
    )

db.close()
