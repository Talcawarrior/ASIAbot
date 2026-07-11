"""Bet placement executor making paper or live trades on Polymarket."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_

from config.settings import Config, bot_config
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio, WeatherMarket
from engine.decision import BetDecision
from utils.formulas import (
    bet_shares,
    max_bet_cap,
    polymarket_fee_from_stake,
    portfolio_total_value,
)
from utils.price_sanity import is_valid_binary_price
from utils.slippage import check_orderbook_depth, estimate_slippage

logger = logging.getLogger("EXECUTOR_BET_PLACER")


class BetPlacer:
    """SADECE bet açar. Karar vermez - engine karar verir."""

    # Statuses that count as "open" for risk/exposure accounting.
    _OPEN_STATUSES = OPEN_BET_STATUSES

    def __init__(self):
        # Lazy-import risk manager to break import cycle:
        #   engine/strategy.py  ->  imports from this module
        #   executor/bet_placer.py  ->  uses engine.strategy.RiskManager
        from engine.strategy import RiskManager

        # NOTE: RiskManager is created WITHOUT a db_session here.
        # The session is bound per-call in place_bet() so that
        # _conservative_portfolio_value() always sees fresh committed data
        # instead of falling back to INITIAL_PORTFOLIO ($1000).
        self.risk_manager = RiskManager()

        # Hard guard: the user requires paper-only mode.
        if Config.DRY_RUN:
            self.ready = False
            logger.info(
                "DRY_RUN=true is enforced. BetPlacer will ONLY emit paper/simulated "
                "orders; the live Polymarket CLOB client is not initialized."
            )
        else:
            self._init_polymarket_client()

    def _init_polymarket_client(self):
        """Polymarket CLOB client hazirla (sadece DRY_RUN=false ise cagrilir)."""
        try:
            from py_clob_client.client import (
                ClobClient,  # pylint: disable=import-error,no-name-in-module
            )

            if not bot_config.polymarket.private_key:
                self.ready = False
                logger.info("Polymarket credentials not found, running in PAPER/SIMULATION trade mode.")
                return

            self.client = ClobClient(
                bot_config.polymarket.api_url,
                key=bot_config.polymarket.private_key,
                chain_id=137,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            self.ready = True
            logger.warning(
                "LIVE TRADING ARMED -- DRY_RUN=false and credentials present. Real orders will be sent to Polymarket."
            )
        except Exception as e:
            logger.warning(f"Polymarket client kurulamadi (PAPER TRADE ACTIVE): {e}")
            self.ready = False

    # ----------------------------------------------------------------------
    # Gate check helper methods (extracted from place_bet for readability)
    # ----------------------------------------------------------------------

    def _check_analysis_exists(self, d: BetDecision, analysis) -> bool:
        """Gate 1: Analysis exists and should_bet is True."""
        d.check("analysis_exists", analysis is not None and analysis.should_bet)
        return d.should_bet

    def _check_edge_positive(self, d: BetDecision, analysis) -> bool:
        """Gate 2: Edge must be >= min_edge from strategy config."""
        edge_val = float(analysis.edge or 0.0)
        _min_edge = float(bot_config.strategy.min_edge) if hasattr(bot_config.strategy, "min_edge") else 0.0
        d.check("edge_positive", edge_val >= _min_edge, edge=edge_val, min_edge=_min_edge)
        return d.should_bet

    def _check_market_exists(self, d: BetDecision, market) -> bool:
        """Gate 3: Market exists."""
        d.check("market_exists", market is not None)
        return d.should_bet

    def _check_circuit_breaker(self, d: BetDecision, session) -> bool:
        """Gate 4: Daily loss limit (circuit breaker) - includes unrealized PnL."""
        if self.risk_manager.is_bot_locked(db_session=session):
            d.check("daily_loss_limit", False, daily_pnl=self.risk_manager.daily_pnl)
            return False
        return True

    def _check_price_valid(self, d: BetDecision, market) -> bool:
        """Gate 5: Price sanity check - skip invalid binary markets."""
        price_valid = is_valid_binary_price(market.yes_price or 0, market.no_price or 0)
        d.check("price_valid", price_valid, yes=market.yes_price, no=market.no_price)
        return d.should_bet

    def _check_target_date_ok(self, d: BetDecision, market) -> bool:
        """Gate 6: Skip resolved markets."""
        _now = datetime.now(timezone.utc).replace(tzinfo=None)
        date_ok = not (market.target_date and market.target_date <= _now)
        d.check("target_date_ok", date_ok, target_date=str(market.target_date) if market.target_date else None)
        return d.should_bet

    def _check_min_entry_price(self, d: BetDecision, market) -> bool:
        """Gate 7: Skip markets with no real liquidity (min_entry_price filter)."""
        market_price = float(market.yes_price or 0.5)
        if hasattr(bot_config.strategy, "min_entry_price"):
            min_price = float(bot_config.strategy.min_entry_price)
        else:
            min_price = float(getattr(self.risk_manager.config, "MIN_ENTRY_PRICE", 0.01))
        d.check("min_entry_price", market_price >= min_price, price=market_price, min_price=min_price)
        return d.should_bet

    def _check_no_existing_bet(self, d: BetDecision, session, market, analysis) -> bool:
        """Gate 8: No existing bet for this market (with cooldown)."""
        _today_start = datetime.now(timezone.utc).replace(tzinfo=None)
        _today_start = _today_start.replace(hour=0, minute=0, second=0, microsecond=0)

        _cooldown_hours = int(os.getenv("REOPEN_COOLDOWN_HOURS", "24"))
        _cooldown_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=_cooldown_hours)

        existing_open = (
            session.query(Bet)
            .filter(
                Bet.market_id == analysis.market_id,
                or_(
                    # 1) Aktif bet varsa engelle
                    Bet.status.in_(OPEN_BET_STATUSES),
                    # 2) Bugun acilmis bet varsa engelle (rejected/failed hariç)
                    and_(
                        Bet.status.notin_(("rejected", "failed")),
                        Bet.placed_at >= _today_start,
                    ),
                    # 3) Son N saatte kapanmis bet varsa engelle (cooldown)
                    and_(
                        Bet.status.notin_(OPEN_BET_STATUSES + ("rejected", "failed")),
                        or_(
                            Bet.closed_at >= _cooldown_cutoff,
                            Bet.settled_at >= _cooldown_cutoff,
                        ),
                    ),
                ),
            )
            .first()
        )
        d.check(
            "no_existing_bet",
            existing_open is None,
            existing_id=existing_open.id if existing_open else None,
            existing_status=existing_open.status if existing_open else None,
            cooldown_hours=_cooldown_hours,
        )
        return d.should_bet

    def _sync_portfolio_value(self, session):
        """Sync RiskManager portfolio_value from DB so risk caps reflect actual portfolio."""
        _pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if _pf and _pf.total_value is not None:
            # Use conservative value (initial + realized only)
            self.risk_manager.update_portfolio(self.risk_manager._conservative_portfolio_value())

    def _calculate_proposed_amount(self, analysis, flat_bet: float) -> float:
        """Calculate proposed bet amount with flat-bet override."""
        proposed_amount = float(analysis.recommended_amount or 0.0)
        if flat_bet > 0.0:
            logger.info(f"Flat-bet override active: ${flat_bet:.2f} per bet (was ${proposed_amount:.2f} from Kelly).")
            proposed_amount = flat_bet
        return proposed_amount

    def _apply_max_bet_cap(self, d: BetDecision, analysis, proposed_amount: float) -> float:
        """Cap 1: per-bet cap (MAX_BET_PCT * portfolio)."""
        from utils.kelly import dynamic_max_bet_pct

        _edge_for_cap = float(analysis.edge or 0.0)
        _dyn_max_pct = dynamic_max_bet_pct(_edge_for_cap, float(self.risk_manager.config.MAX_BET_PCT))
        _conservative = float(self.risk_manager._conservative_portfolio_value())
        max_bet = max_bet_cap(_conservative, _dyn_max_pct)
        if proposed_amount > max_bet:
            logger.warning(
                f"Risk cap: Market {analysis.market_id} amount ${proposed_amount:.2f} "
                f"exceeds per-bet max ${max_bet:.2f} (edge={_edge_for_cap:.3f}, "
                f"dyn_pct={_dyn_max_pct:.3f}) — clamping."
            )
            proposed_amount = max_bet
        d.set_param("max_bet_cap", max_bet)
        d.set_param("dynamic_max_bet_pct", _dyn_max_pct)
        return proposed_amount

    def _check_exposure_cap(self, d: BetDecision, session, analysis, proposed_amount: float) -> bool:
        """Cap 2: total exposure cap (TOTAL_EXPOSURE_PCT * conservative portfolio)."""
        current_exposure = (
            session.query(func.coalesce(func.sum(Bet.amount), 0.0)).filter(Bet.status.in_(self._OPEN_STATUSES)).scalar()
        ) or 0.0
        current_exposure = float(current_exposure)
        exposure_ok = self.risk_manager.check_exposure_cap(current_exposure, proposed_amount)
        conservative_value = self.risk_manager._conservative_portfolio_value()
        max_exposure = float(conservative_value) * float(self.risk_manager.config.TOTAL_EXPOSURE_PCT)
        d.check(
            "exposure_cap",
            exposure_ok,
            current=current_exposure,
            proposed=proposed_amount,
            max_exposure=max_exposure,
            conservative=conservative_value,
        )
        if not exposure_ok:
            logger.warning(
                f"Risk cap: Market {analysis.market_id} rejected — exposure would "
                f"reach ${current_exposure + proposed_amount:.2f}, "
                f"exceeding cap ${max_exposure:.2f} "
                f"(conservative=${conservative_value:.2f})."
            )
            # Record a synthetic "rejected" bet row for audit visibility
            rejected = Bet(
                market_id=analysis.market_id,
                analysis_id=analysis.id,
                city=analysis.market.city if analysis.market else "unknown",
                city_code=analysis.market.city_code if analysis.market else "unknown",
                side=analysis.recommended_side,
                amount=proposed_amount,
                price=(analysis.market.yes_price if analysis.recommended_side == "YES" else analysis.market.no_price),
                status="rejected",
                error_message=(
                    f"Exposure cap: ${current_exposure:.2f} + ${proposed_amount:.2f} > "
                    f"${max_exposure:.2f} (conservative=${conservative_value:.2f})"
                ),
            )
            session.add(rejected)
            session.commit()
            d.log(logging.WARNING)
            return False
        return True

    def _check_city_cap(self, d: BetDecision, session, analysis, market, proposed_amount: float) -> bool:
        """Cap 3: city cap (CITY_CAP per city)."""
        city_key = (market.city or "").lower()
        city_open_count = (
            session.query(func.count(Bet.id))  # pylint: disable=not-callable
            .join(WeatherMarket, Bet.market_id == WeatherMarket.id)
            .filter(
                Bet.status.in_(self._OPEN_STATUSES),
                func.lower(WeatherMarket.city) == city_key,
            )
            .scalar()
        ) or 0
        city_cap = int(self.risk_manager.config.CITY_CAP)
        city_ok = int(city_open_count) < city_cap
        d.check("city_cap", city_ok, city=market.city, open_count=int(city_open_count), max_city=city_cap)
        if not city_ok:
            logger.warning(
                f"Risk cap: Market {market.id} rejected — city cap "
                f"({city_open_count}/{city_cap}) "
                f"reached for {market.city}."
            )
            rejected = Bet(
                market_id=analysis.market_id,
                analysis_id=analysis.id,
                city=market.city,
                city_code=market.city_code,
                side=analysis.recommended_side,
                amount=proposed_amount,
                price=(market.yes_price if analysis.recommended_side == "YES" else market.no_price),
                status="rejected",
                error_message=f"City cap: {city_open_count}/{city_cap} for {market.city}",
            )
            session.add(rejected)
            session.commit()
            d.log(logging.WARNING)
            return False
        return True

    def _resolve_condition_id(self, market, analysis) -> str | None:
        """Extract condition_id from market.raw_data for slippage & depth check."""
        condition_id = None
        try:
            raw = json.loads(market.raw_data) if market.raw_data else {}
            for tok in raw.get("tokens", []):
                if tok.get("outcome", "").upper() == (analysis.recommended_side or "").upper():
                    condition_id = tok.get("condition_id") or tok.get("token_id")
                    break
        except (json.JSONDecodeError, TypeError):
            pass
        return condition_id

    def _calculate_fill_price(self, market, analysis, slip_est) -> float:
        """Resolve fill price for the chosen side, adjusted for slippage."""
        raw_fill = market.yes_price if analysis.recommended_side == "YES" else market.no_price
        raw_fill = float(raw_fill) if raw_fill is not None else 0.0
        fill_price = raw_fill * (1.0 + slip_est.slippage_pct)
        fill_price = max(0.01, min(0.99, round(fill_price, 4)))
        return fill_price

    def _check_max_entry_price(self, d: BetDecision, fill_price: float) -> bool:
        """Gate: skip if fill price > 0.97 (low margin, fees eat the profit)."""
        MAX_ENTRY_PRICE = 0.97
        d.check("max_entry_price", fill_price <= MAX_ENTRY_PRICE, fill_price=fill_price, max_price=MAX_ENTRY_PRICE)
        return d.should_bet

    def _check_orderbook_depth(
        self, d: BetDecision, session, condition_id, analysis, fill_price, proposed_amount: float
    ) -> bool:
        """Gate: orderbook depth check."""
        min_depth = float(getattr(bot_config.strategy, "min_depth_usd", 0.0) or 0.0)
        depth_ok, depth_usd = check_orderbook_depth(
            condition_id,
            analysis.recommended_side or "YES",
            fill_price,
            proposed_amount,
            min_depth_usd=min_depth,
        )
        if not depth_ok:
            logger.warning(
                f"Market {analysis.market_id}: depth filter rejected (${depth_usd:.2f} < ${min_depth:.2f} min)"
            )
            d.check("depth_ok", False, depth_usd=depth_usd, min_depth=min_depth)
            rejected = Bet(
                market_id=analysis.market_id,
                analysis_id=analysis.id,
                city=analysis.market.city,
                city_code=analysis.market.city_code,
                side=analysis.recommended_side,
                amount=proposed_amount,
                price=fill_price,
                status="rejected",
                error_message=f"Depth filter: ${depth_usd:.2f} < ${min_depth:.2f}",
            )
            session.add(rejected)
            session.commit()
            d.log(logging.WARNING)
            return False
        d.check("depth_ok", True, depth_usd=depth_usd, min_depth=min_depth)
        return True

    def _calculate_fee_and_shares(self, market, analysis, fill_price, proposed_amount: float):
        """Calculate Polymarket taker fee and shares."""
        fee_rate = getattr(market, "fee_rate", None) or Config.WEATHER_FEE_RATE
        entry_fee = polymarket_fee_from_stake(proposed_amount, fill_price, fee_rate)
        shares = bet_shares(proposed_amount, fill_price)
        return entry_fee, shares

    def _create_bet_object(self, market, analysis, fill_price, proposed_amount, entry_fee, shares, fair_value):
        """Create Bet object with all required fields."""
        bet = Bet(
            market_id=analysis.market_id,
            analysis_id=analysis.id,
            city=market.city,
            city_code=market.city_code,
            side=analysis.recommended_side,
            amount=proposed_amount,
            stake_amount=proposed_amount,
            price=fill_price,
            entry_price=fill_price,
            shares=shares,
            current_price=fill_price,
            status="pending",
            fair_value=fair_value,
            expected_value=float(analysis.edge or 0.0),
            entry_fee=round(entry_fee, 4),
        )
        bet.potential_payout = bet.amount / bet.price if bet.price > 0 else 0
        return bet

    def _build_ladder_orders(self, bet, fill_price, proposed_amount: float, edge_val: float):
        """Build paper ladder orders based on edge."""
        ladder_orders = []
        if edge_val >= 0.05:
            if edge_val >= 0.20:
                splits = [(1, 0.70), (2, 0.20), (3, 0.10)]
                price_factors = [1.0, 1.02, 1.05]
                ladder_mode = "pyramiding"
            elif edge_val >= 0.10:
                splits = [(1, 0.50), (2, 0.30), (3, 0.20)]
                price_factors = [1.0, 0.98, 0.95]
                ladder_mode = "averaging"
            else:
                splits = [(1, 0.40), (2, 0.35), (3, 0.25)]
                price_factors = [1.0, 0.98, 0.95]
                ladder_mode = "conservative_averaging"

            for (lvl, pct), pf in zip(splits, price_factors):
                lvl_amount = round(proposed_amount * pct, 2)
                lvl_price = fill_price * pf
                lvl_price = max(0.01, min(0.99, round(lvl_price, 4)))
                lvl_shares = round(lvl_amount / lvl_price, 4) if lvl_price > 0 else 0.0
                ladder_orders.append(
                    {
                        "level": lvl,
                        "price": lvl_price,
                        "amount": lvl_amount,
                        "shares": lvl_shares,
                        "status": "pending",
                        "mode": ladder_mode,
                    }
                )
        return ladder_orders

    def _execute_live_order(self, bet, market, analysis):
        """Execute live order on Polymarket."""
        from py_clob_client.order_builder.constants import BUY

        order = self.client.create_and_post_order(
            {
                "token_id": self._get_token_id(market, analysis.recommended_side),
                "price": bet.price,
                "size": bet.amount / bet.price,
                "side": BUY,
            }
        )
        bet.order_id = order.get("orderID")
        bet.status = "placed"
        bet.placed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def _execute_paper_order(self, bet):
        """Execute paper order (simulation)."""
        bet.status = "placed"
        bet.placed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def _get_token_id(self, market, side):
        """Extract token_id from market.raw_data for the given side."""
        try:
            raw = json.loads(market.raw_data) if market.raw_data else {}
            for tok in raw.get("tokens", []):
                if tok.get("outcome", "").upper() == side.upper():
                    return tok.get("condition_id") or tok.get("token_id")
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def place_bet(self, analysis_id: int, session=None) -> Bet | None:
        """Analiz sonucuna göre bet aç.

        Optional session for batched cycles — when provided, reuses the
        caller's DB session so freshly-written Analysis records from the
        current cycle are visible.
        """
        d = BetDecision(market_id=f"analysis:{analysis_id}")
        from database.db import get_session_or

        with get_session_or(session) as session:
            analysis = session.query(Analysis).filter_by(id=analysis_id).first()
            if not self._check_analysis_exists(d, analysis):
                d.log(logging.DEBUG)
                return None

            if not self._check_edge_positive(d, analysis):
                d.log(logging.WARNING)
                return None

            market = session.query(WeatherMarket).filter_by(id=analysis.market_id).first()
            if not self._check_market_exists(d, market):
                d.log(logging.DEBUG)
                return None
            d.market_id = market.id

            if not self._check_circuit_breaker(d, session):
                d.log(logging.WARNING)
                return None

            if not self._check_price_valid(d, market):
                d.log(logging.DEBUG)
                return None

            if not self._check_target_date_ok(d, market):
                d.log(logging.DEBUG)
                return None

            if not self._check_min_entry_price(d, market):
                d.log(logging.DEBUG)
                return None

            if not self._check_no_existing_bet(d, session, market, analysis):
                d.log(logging.INFO)
                return None

            self._sync_portfolio_value(session)

            flat_bet = float(getattr(self.risk_manager.config, "FLAT_BET_USD", 0.0) or 0.0)
            proposed_amount = self._calculate_proposed_amount(analysis, flat_bet)

            proposed_amount = self._apply_max_bet_cap(d, analysis, proposed_amount)

            if not self._check_exposure_cap(d, session, analysis, proposed_amount):
                return None

            if not self._check_city_cap(d, session, analysis, market, proposed_amount):
                return None

            condition_id = self._resolve_condition_id(market, analysis)

            slip_est = estimate_slippage(
                float(market.yes_price if analysis.recommended_side == "YES" else market.no_price or 0.0),
                stake_usd=proposed_amount,
                condition_id=condition_id,
            )
            fill_price = self._calculate_fill_price(market, analysis, slip_est)

            if not self._check_max_entry_price(d, fill_price):
                return None

            if not self._check_orderbook_depth(d, session, condition_id, analysis, fill_price, proposed_amount):
                return None

            entry_fee, shares = self._calculate_fee_and_shares(market, analysis, fill_price, proposed_amount)

            fair_value = float(analysis.estimated_probability or 0.5)
            bet = self._create_bet_object(market, analysis, fill_price, proposed_amount, entry_fee, shares, fair_value)

            edge_val = float(analysis.edge or 0.0)
            ladder_orders = self._build_ladder_orders(bet, fill_price, proposed_amount, edge_val)

            _live_allowed = (not Config.DRY_RUN) and os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
            if self.ready and _live_allowed:
                self._execute_live_order(bet, market, analysis)
            else:
                self._execute_paper_order(bet)

            from utils.accounting import debit_stake

            initial_stake = proposed_amount
            if ladder_orders:
                l1_amount = ladder_orders[0].get("amount") if isinstance(ladder_orders[0], dict) else None
                if l1_amount and l1_amount > 0:
                    initial_stake = l1_amount
                    ladder_orders[0]["status"] = "filled"
                    ladder_orders[0]["filled_at"] = datetime.now(timezone.utc).isoformat()
                    bet.ladder_data = json.dumps(ladder_orders)

            try:
                debit_stake(session, initial_stake, f"bet_open:{bet.market_id}")
                if entry_fee > 0:
                    debit_stake(session, entry_fee, f"bet_fee:{bet.market_id}")
            except ValueError as e:
                logger.error("Cannot open bet %s: %s", bet.market_id, e)
                bet.status = "failed"
                bet.error_message = str(e)
                session.add(bet)
                session.commit()
                return bet

            portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                open_exposure = (
                    session.query(func.coalesce(func.sum(Bet.amount), 0.0))
                    .filter(Bet.status.in_(OPEN_BET_STATUSES))
                    .scalar()
                ) or 0.0
                portfolio.current_value = portfolio_total_value(portfolio.cash_balance or 0.0, float(open_exposure))
                portfolio.last_updated = datetime.now(timezone.utc).replace(tzinfo=None)

            session.add(bet)
            session.commit()
            d.final_amount = proposed_amount
            d.set_param("entry_fee", round(entry_fee, 4))
            d.set_param("fill_price", fill_price)
            d.set_param("shares", shares)
            d.set_param("side", analysis.recommended_side)
            d.set_param("status", bet.status)
            d.log(logging.INFO)
            return bet

    def _get_token_id(self, market, side: str) -> str:
        """Market'ten token ID al."""
        raw = json.loads(market.raw_data) if market.raw_data else {}
        tokens = raw.get("tokens", [])
        for token in tokens:
            if token.get("outcome", "").upper() == side.upper():
                return token.get("token_id")
        raise ValueError(f"Token ID bulunamadı: {side}")

    def place_all_pending(self, session=None) -> int:
        """should_bet=True olan tum analizler icin bet ac.

        Optional session for batched cycles — when provided, reuses the
        caller's session instead of creating a new one. This ensures
        freshly-written Analysis records from the current cycle's
        run_analyze() are visible to bet placement.
        """
        placed = 0
        # Build mapping of analysis_id -> market_id + set of markets that
        # already have bets, inside a single session.
        aid_to_market: dict[int, str] = {}
        markets_with_bets: set[str] = set()

        from database.db import get_session_or

        with get_session_or(session) as sess:
            # Only use the LATEST analysis per market (highest id).
            # This prevents old analyses with stale recommended_amount
            # (e.g. pre-config-change $29.70) from being placed.
            from sqlalchemy import func as sa_func

            subq = (
                sess.query(
                    Analysis.market_id,
                    sa_func.max(Analysis.id).label("max_id"),
                )
                .group_by(Analysis.market_id)
                .subquery()
            )
            pending = (
                sess.query(Analysis)
                .join(subq, Analysis.id == subq.c.max_id)
                .filter(Analysis.should_bet.is_(True))
                .join(WeatherMarket, Analysis.market_id == WeatherMarket.id)
                .order_by(Analysis.edge.desc())
                .all()
            )

            # Dedup: skip market_ids that already have a bet (OPEN or placed today).
            # Prevents re-betting the same market across scan cycles on the same day.
            market_ids = {a.market_id for a in pending}
            if market_ids:
                _today_start = datetime.now(timezone.utc).replace(tzinfo=None)
                _today_start = _today_start.replace(hour=0, minute=0, second=0, microsecond=0)
                existing_rows = (
                    sess.query(Bet.market_id)
                    .filter(
                        Bet.market_id.in_(list(market_ids)),
                        or_(
                            Bet.status.in_(OPEN_BET_STATUSES),
                            and_(
                                Bet.status.notin_(("rejected", "failed")),
                                Bet.placed_at >= _today_start,
                            ),
                        ),
                    )
                    .all()
                )
                markets_with_bets = {row[0] for row in existing_rows if row[0] is not None}

            # --- Cooldown: skip markets that were recently closed (take-profit,
            #     stop-loss, or stale_cleanup).  Prevents the bot from immediately
            #     re-opening the same market after an early exit.  The cooldown
            #     window is configurable via REOPEN_COOLDOWN_HOURS env var
            #     (default 24 hours).  A market that was settled naturally
            #     (won/lost) is also blocked for the cooldown period so that
            #     the bot doesn't re-enter a resolved question before new data
            #     arrives.
            _cooldown_hours = int(os.getenv("REOPEN_COOLDOWN_HOURS", "24"))
            _cooldown_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=_cooldown_hours)
            if market_ids:
                cooldown_rows = (
                    sess.query(Bet.market_id)
                    .filter(
                        Bet.market_id.in_(list(market_ids)),
                        Bet.status.notin_(OPEN_BET_STATUSES + ("rejected", "failed")),
                        or_(
                            Bet.closed_at >= _cooldown_cutoff,
                            Bet.settled_at >= _cooldown_cutoff,
                        ),
                    )
                    .all()
                )
                _cooldown_markets = {row[0] for row in cooldown_rows if row[0] is not None}
                for m_id in _cooldown_markets:
                    markets_with_bets.add(m_id)
                if _cooldown_markets:
                    logger.info(
                        "Cooldown: %d market blocked (last %dh) from re-opening: %s",
                        len(_cooldown_markets),
                        _cooldown_hours,
                        list(_cooldown_markets)[:5],
                    )

            # --- City+threshold dedup: skip if there's already an open bet on
            #     the same city + metric + threshold + target_date, even if the
            #     Polymarket market_id differs (rare but possible with duplicate
            #     or near-duplicate questions).
            if pending:
                open_city_dup = (
                    sess.query(
                        func.lower(WeatherMarket.city).label("city_l"),
                        WeatherMarket.metric,
                        WeatherMarket.threshold,
                        WeatherMarket.target_date,
                    )
                    .join(Bet, Bet.market_id == WeatherMarket.id)
                    .filter(Bet.status.in_(OPEN_BET_STATUSES))
                    .group_by(
                        func.lower(WeatherMarket.city),
                        WeatherMarket.metric,
                        WeatherMarket.threshold,
                        WeatherMarket.target_date,
                    )
                    .all()
                )
                _city_dup_set = {(r.city_l, r.metric, r.threshold, r.target_date) for r in open_city_dup}
                # Build a lookup from analysis.market_id -> (city, metric, threshold, date)
                _mkt_lookup = {}
                if pending:
                    mkt_ids_for_dedup = list({a.market_id for a in pending})
                    _city_markets = {
                        m.id: m for m in sess.query(WeatherMarket).filter(WeatherMarket.id.in_(mkt_ids_for_dedup))
                    }
                    for a in pending:
                        m = _city_markets.get(a.market_id)
                        if m:
                            _mkt_lookup[a.market_id] = (
                                (m.city or "").lower(),
                                m.metric,
                                m.threshold,
                                m.target_date,
                            )
                for a in pending:
                    key = _mkt_lookup.get(a.market_id)
                    if key and key in _city_dup_set:
                        markets_with_bets.add(a.market_id)
                _city_dup_count = sum(1 for a in pending if _mkt_lookup.get(a.market_id) in _city_dup_set)
                if _city_dup_count:
                    logger.info(
                        "City+threshold dedup: %d analysis skipped (same city/metric/threshold/date already open)",
                        _city_dup_count,
                    )

            # --- Sort by target_date priority FIRST (farthest date opens first):
            #     Markets with more time to close are prioritised so they get
            #     filled and settled before nearer-term markets.
            #     Within the same tier (same days-out), highest edge wins.
            #     Tier thresholds:
            #       tier 3 (highest):  >48h to close  (~2+ days out)
            #       tier 2:            >24h to close  (~1+ day out)
            #       tier 1 (lowest):   <=24h to close (today)
            if pending:
                mkt_ids = list({a.market_id for a in pending})
                _markets = {m.id: m for m in sess.query(WeatherMarket).filter(WeatherMarket.id.in_(mkt_ids))}
                _now_utc = datetime.now(timezone.utc)

                def _priority_key(a: Analysis) -> float:
                    m = _markets.get(a.market_id)
                    if m is None or a.edge is None:
                        return 0.0
                    td = m.target_date
                    if td:
                        if td.tzinfo is None:
                            td = td.replace(tzinfo=timezone.utc)
                        hours_left = (td - _now_utc).total_seconds() / 3600.0
                    else:
                        hours_left = -1.0

                    if hours_left > 48:
                        tier = 3
                    elif hours_left > 24:
                        tier = 2
                    else:
                        tier = 1

                    return tier * 1000.0 + float(a.edge) * 100.0

                pending.sort(key=_priority_key, reverse=True)
                logger.info(
                    "Pending sorted by tier: top3=%s",
                    [
                        (
                            a.market_id,
                            _markets.get(a.market_id).city if _markets.get(a.market_id) else "?",
                            round(a.edge * 100, 1),
                        )
                        for a in pending[:3]
                    ],
                )

            for a in pending:
                aid_to_market[a.id] = a.market_id

        for aid, mkt_id in aid_to_market.items():
            if mkt_id in markets_with_bets:
                logger.debug(
                    "Market %s already has a bet, skipping analysis %d",
                    mkt_id,
                    aid,
                )
                continue
            try:
                bet = self.place_bet(aid, session=sess)
                if bet is not None:
                    placed += 1
                    # Track this market to skip duplicate analyses in same batch
                    markets_with_bets.add(mkt_id)
            except Exception as e:
                logger.error(f"Bet hatasi (analysis {aid}): {e}")
                continue

        return placed
