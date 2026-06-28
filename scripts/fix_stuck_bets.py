"""Manually settle two stuck bets that haven't closed.

Bet 11712 (New York, test-e2e-001): Test market, Polymarket doesn't have it.
  → Cancel and refund.

Bet 13437 (Hong Kong, 2663367): NO side, entry=0.5125, current=0.9995.
  → 48h fallback hasn't triggered yet but NO clearly won.
  → Settle as win.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import get_session
from database.models import Bet, OPEN_BET_STATUSES
from datetime import datetime, timezone
from utils.accounting import credit_sale, credit_settlement


def fix_stuck_bets():
    with get_session() as session:
        # 1. New York (test market) — cancel
        bet1 = session.query(Bet).filter(Bet.id == 11712).first()
        if bet1 and bet1.status in OPEN_BET_STATUSES:
            amount = float(bet1.amount or 0)
            bet1.status = "cancelled"
            bet1.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
            bet1.close_reason = "stale_test_market"
            credit_sale(session, amount, f"manual_cancel:bet_{bet1.id}:test_market")
            print(f"Bet 11712 (NY test): CANCELLED, refund=${amount:.2f}")
        else:
            print(
                f"Bet 11712: already settled/cancelled ({bet1.status if bet1 else 'NOT FOUND'})"
            )

        # 2. Hong Kong — settle as win (NO won, price=0.9995)
        bet2 = session.query(Bet).filter(Bet.id == 13437).first()
        if bet2 and bet2.status in OPEN_BET_STATUSES:
            stake = float(bet2.amount or 0)
            entry = float(bet2.entry_price or 0.5125)
            payout = stake / entry if entry > 0 else 0
            fee = (payout - stake) * 0.02
            realized_pnl = payout - stake - fee
            bet2.status = "won"
            bet2.pnl = round(realized_pnl, 2)
            bet2.realized_pnl = round(realized_pnl, 2)
            bet2.unrealized_pnl = 0
            bet2.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
            bet2.close_reason = "fallback_price:NO_won_0.9995"
            credit_settlement(session, payout, fee, "settle:2663367:won")
            print(
                f"Bet 13437 (HK): WON, stake=${stake:.2f}, payout=${payout:.2f}, fee=${fee:.2f}, pnl=${realized_pnl:.2f}"
            )
        else:
            print(
                f"Bet 13437: already settled ({bet2.status if bet2 else 'NOT FOUND'})"
            )

        session.commit()
        print("Done!")


if __name__ == "__main__":
    fix_stuck_bets()
