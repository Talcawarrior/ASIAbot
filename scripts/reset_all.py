"""Full bot reset: clear all operational data, reset portfolio to $1,000.

Run: python scripts/reset_all.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import get_session
from database.models import Analysis, Bet, Portfolio, WeatherForecast, WeatherMarket


def main():
    with get_session() as session:
        # Count before
        n_bets = session.query(Bet).count()
        n_analyses = session.query(Analysis).count()
        n_markets = session.query(WeatherMarket).count()
        n_forecasts = session.query(WeatherForecast).count()

        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        old_cash = pf.cash_balance if pf else 0

        print("=== BOT RESET ===")
        print(f"  bets:          {n_bets}")
        print(f"  analyses:      {n_analyses}")
        print(f"  markets:       {n_markets}")
        print(f"  forecasts:     {n_forecasts}")
        print(f"  cash_balance:  ${old_cash:,.2f}")
        print()

        # Delete operational data
        session.query(Bet).delete()
        session.query(Analysis).delete()
        session.query(WeatherMarket).delete()
        session.query(WeatherForecast).delete()

        # Reset portfolio
        if not pf:
            pf = Portfolio(id=1)
            session.add(pf)

        pf.cash_balance = 1000.0
        pf.initial_value = 1000.0
        pf.current_value = 1000.0
        pf.total_value = 1000.0
        pf.total_realized_pnl = 0.0
        pf.daily_pnl = 0.0
        pf.total_won = 0
        pf.total_lost = 0

        session.commit()

        print("  [OK] bets deleted")
        print("  [OK] analyses deleted")
        print("  [OK] markets deleted")
        print("  [OK] forecasts deleted")
        print("  [OK] portfolio reset -> $1,000.00")
        print()
        print("  model_performance: KEPT (model accuracy data)")
        print("  historical_calibrations: KEPT (calibration data)")
        print()
        print("=== RESET COMPLETE ===")


if __name__ == "__main__":
    main()
