"""Matematiksel olasılık, Kelly kriteri hesaplayıcısı ve WeatherEngine konsensüs birleşimi."""

import asyncio
import json
import logging
import math
import time
from datetime import UTC, datetime

import aiohttp

from asi_engine.calibration_engine import CalibrationEngine
from config.settings import Config, bot_config, config
from database.db import get_session_or
from database.models import Analysis, Portfolio, WeatherForecast, WeatherMarket
from utils.formulas import max_bet_cap
from utils.kelly import kelly_fraction as _kelly_fraction
from utils.price_sanity import is_valid_binary_price
from utils.probability import compute_effective_min_edge
from utils.probability import estimate_probability as _estimate_probability
from utils.slippage import (
    adjust_edge_for_costs,
    adjust_kelly_for_slippage,
    estimate_slippage,
)
from utils.weights_store import load_weights

logger = logging.getLogger("ENGINE_CALCULATOR")

# BUG-3 FIX: Global 429 cooldown. When ANY city gets a 429 from Open-Meteo,
# all other cities wait this many seconds before retrying. This prevents
# 65 cities × 120s exponential backoff = 227 min total blocking.
# Instead, one 429 cools down the entire batch for 30s, then all resume.
_GLOBAL_429_COOLDOWN_S = 30.0
_global_429_until: float = 0.0


def adjusted_edge(
    raw_edge: float,
    days_ahead: int,
    market_type: str,
    side: str | None,
    ensemble_spread: float,
    forecast_rmse: float | None = None,
) -> float:
    """
    Adjusted edge formula incorporating time, market type, side, spread, and RMSE penalties.

    score = raw_edge × time_coeff(days) × type_coeff(market) × side_coeff(side)
            × (1 / forecast_rmse(days)²) × spread_penalty(spread)

    All coefficients come from bot_config.strategy (derived from historical ROI analysis).
    """
    from config.settings import bot_config

    s = bot_config.strategy

    # Time coefficient (default: 0-1d: 0.25, 1-2d: 1.0, 2-3d: 1.1, 3+: 1.0)
    time_coeff = s.time_coefficients.get(min(days_ahead, 3), 1.0)

    # Market type coefficient (temp_max: 1.0, temp_min: 0.02)
    type_coeff = s.market_type_coeff.get(market_type, 1.0)

    # Side coefficient (NO: 1.0, YES: 0.5 — reduce but don't eliminate YES bets)
    side_coeff = 1.0
    if side is not None:
        side_coeff = s.side_coeff.get(side.upper(), 1.0)

    # Forecast RMSE penalty: 1 / rmse^2
    rmse = s.forecast_rmse_by_horizon.get(min(days_ahead, 3), 1.5) if forecast_rmse is None else forecast_rmse
    rmse_penalty = 1.0 / (rmse * rmse) if rmse > 0 else 1.0

    # Spread penalty: high ensemble spread = low confidence
    spread_penalty = s.spread_penalty_factor if ensemble_spread > s.spread_penalty_threshold else 1.0

    return raw_edge * time_coeff * type_coeff * side_coeff * rmse_penalty * spread_penalty


def _utcnow_naive() -> datetime:
    """Return naive UTC now. All DB datetimes are naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class Calculator:
    """Calculates forecasting probability, Kelly stake sizes, and analyzes markets."""

    def estimate_probability(
        self,
        forecasts: list[float],
        threshold: float,
        days_ahead: int,
        market_type: str = "HIGH",
        range_low: float | None = None,
        range_high: float | None = None,
    ) -> float:
        """Tahmin değerlerinden, market tipine göre YES olasılığını hesapla.

        Delegates to :func:`utils.probability.estimate_probability`.
        """
        if not forecasts:
            return 0.5

        mean = sum(forecasts) / len(forecasts)

        if len(forecasts) > 1:
            variance = sum((x - mean) ** 2 for x in forecasts) / (len(forecasts) - 1)
            std = math.sqrt(variance)
        else:
            std = 2.0  # Default 2C uncertainty for single source

        return _estimate_probability(
            mean=mean,
            std=std,
            threshold=threshold,
            days_ahead=days_ahead,
            market_type=market_type,
            range_low=range_low,
            range_high=range_high,
        )

    # NOTE: Kelly fraction is NOT duplicated here.
    # Use utils.kelly.kelly_fraction() instead of a local copy.
    # This method wrapper exists only to apply the strategy's kelly_fraction.
    def kelly_criterion(self, prob: float, price: float, fraction: float = 0.15) -> float:
        """Wrapper around utils.kelly.kelly_fraction + fraction multiplier."""
        f_star = _kelly_fraction(prob, price)
        return f_star * fraction

    def analyze_market(self, market_id: str, session=None, forecast_cache: dict | None = None) -> Analysis | None:
        """Bir marketi analiz et. Optional session for batched cycles.

        Optional forecast_cache: pre-fetched forecasts from run_analyze's
        bulk query. Keyed by (market_id, metric) -> {source: WeatherForecast}.
        When provided, skips the per-market forecast DB query (biggest
        performance win for 339+ market cycles).
        """
        with get_session_or(session) as session:
            market = session.query(WeatherMarket).filter_by(id=market_id).first()
            if not market:
                logger.warning(f"Market bulunamadı: {market_id}")
                return None

            if not all([market.city, market.threshold is not None, market.target_date, market.metric]):
                logger.warning(f"Market eksik bilgi: {market_id}")
                return None

            # Price sanity check - skip invalid binary markets
            if not is_valid_binary_price(market.yes_price or 0, market.no_price or 0):
                logger.debug(
                    f"Market {market_id}: invalid prices yes={market.yes_price}, no={market.no_price}, skipping"
                )
                return None

            # Skip already-resolved markets (lookahead bias guard)
            if market.target_date <= datetime.now(UTC).replace(tzinfo=None):
                logger.debug(f"Market {market_id}: target_date {market.target_date} already passed, skipping")
                return None

            # Skip markets with no real liquidity (price too low for paper realism)
            # The min_entry_price threshold is a Karpathy-search-discovered
            # lever that filters out long-shot bets (the source of the
            # asymmetric-payoff bleed where a single low-price loss wipes
            # out dozens of small wins).
            market_price = market.yes_price or 0.5
            min_price = getattr(bot_config.strategy, "min_entry_price", None) or getattr(
                bot_config, "MIN_ENTRY_PRICE", 0.01
            )
            if market_price < min_price:
                logger.debug(f"Market {market_id}: price {market_price:.4f} < min_entry_price {min_price}, skipping")
                return None

            # Karpathy-search-discovered inefficiency gate. Only bet when
            # the market price is mispriced in our favour by at least
            # `inefficiency_min`. We approximate the "naive fair price" by
            # the simple average of the YES/NO prices (0.5 midpoint adjusted
            # by yes_price deviation), and the inefficiency is the residual
            # after we compute our own estimate_probability below.
            #
            # This is a soft gate — we evaluate it AFTER we know our own
            # estimate, then check the implied market inefficiency.
            inefficiency_min = getattr(bot_config.strategy, "inefficiency_min", -1.0)

            # En son tahminleri al — query by market.metric directly.
            # If forecast_cache is provided (bulk mode), use it instead of per-market query.
            if forecast_cache is not None:
                cache_key = (market_id, market.metric)
                source_forecasts = forecast_cache.get(cache_key, {})
                # Convert to same format as DB query results
                latest_by_source = {}
                source_weights = {}
                for source_name, f in source_forecasts.items():
                    latest_by_source[source_name] = f.predicted_value
                    source_weights[source_name] = f.model_weight or 0.0
                forecast_values = list(latest_by_source.values())
            else:
                forecasts = (
                    session.query(WeatherForecast)
                    .filter(
                        WeatherForecast.market_id == market_id,
                        WeatherForecast.metric == market.metric,
                    )
                    .order_by(WeatherForecast.fetched_at.desc())
                    .all()
                )

                # Her kaynaktan en son tahmini al + ağırlıkları topla
                latest_by_source = {}
                source_weights = {}
                for f in forecasts:
                    if f.source not in latest_by_source:
                        latest_by_source[f.source] = f.predicted_value
                        source_weights[f.source] = f.model_weight or 0.0

                forecast_values = list(latest_by_source.values())

            if len(forecast_values) < bot_config.strategy.min_sources:
                logger.info(
                    f"Market {market_id}: Yetersiz kaynak ({len(forecast_values)}/{bot_config.strategy.min_sources})"
                )

            # Compute weighted std early — needed for both consensus and per-model probs
            total_weight = sum(source_weights.get(s, 0.0) for s in latest_by_source)
            if forecast_values and len(forecast_values) > 1:
                if total_weight > 0:
                    # Weighted average
                    avg = sum(latest_by_source[s] * source_weights.get(s, 0.0) for s in latest_by_source) / total_weight
                    # Weighted std
                    std_val = math.sqrt(
                        sum(source_weights.get(s, 0.0) * (latest_by_source[s] - avg) ** 2 for s in latest_by_source)
                        / total_weight
                    )
                else:
                    # Fallback to simple average if no weights
                    avg = sum(forecast_values) / len(forecast_values)
                    std_val = math.sqrt(sum((x - avg) ** 2 for x in forecast_values) / (len(forecast_values) - 1))
            else:
                avg = forecast_values[0] if forecast_values else 0.5
                std_val = None

            # days_ahead: use CALENDAR date difference (not timedelta) to avoid
            # SQLite microsecond truncation causing 23h59m → days_ahead=0.
            # Calendar arithmetic: target=2026-07-09, now=2026-07-08 → 1 day.
            target_date_obj = market.target_date.date() if hasattr(market.target_date, "date") else market.target_date
            now_date = datetime.now(UTC).date()
            days_ahead = (target_date_obj - now_date).days
            days_ahead_for_check = max(days_ahead, 1)

            # Olasılık hesapla — weighted mean/std ile (market_type-aware)
            # RANGE markets: pass explicit bucket bounds if stored
            range_low = None
            range_high = None
            if (market.market_type or "").upper() == "RANGE":
                if market.threshold_low is not None and market.threshold_high is not None:
                    range_low = float(market.threshold_low)
                    range_high = float(market.threshold_high)
            total_std = float(std_val) if std_val is not None else 2.0
            estimated_prob = _estimate_probability(
                mean=avg,
                std=total_std,
                threshold=float(market.threshold or 0),
                days_ahead=days_ahead_for_check,
                market_type=(market.market_type or "HIGH"),
                range_low=range_low,
                range_high=range_high,
            )

            # Per-model probabilities for SIA weight optimization
            model_temps = {src: float(val) for src, val in latest_by_source.items() if val is not None}
            total_std = float(std_val) if std_val is not None else 2.0
            model_probs = {}
            for mn, mt in model_temps.items():
                mp = _estimate_probability(
                    mean=mt,
                    std=total_std,
                    threshold=float(market.threshold or 0),
                    days_ahead=days_ahead_for_check,
                    market_type=(market.market_type or "HIGH"),
                )
                model_probs[mn] = mp
            model_predictions_json = json.dumps(
                {
                    "model_temps": model_temps,
                    "model_probs": model_probs,
                }
            )

            market_implied = market.yes_price or 0.5

            # ── Market blend ───────────────────────────────────────────
            # Blend model probability with market implied probability to
            # prevent extreme edges from model overconfidence.
            # blend_weight read from bot_config.strategy (default 0.65),
            # auto-optimized by SIA/ASI-Evolve/Karpathy 3-layer stack.
            bw = bot_config.strategy.blend_weight
            if market_implied and 0.01 < market_implied < 0.99:
                b_prob = bw * estimated_prob + (1 - bw) * market_implied
            else:
                b_prob = estimated_prob

            raw_edge = b_prob - market_implied

            if raw_edge > 0:
                # YES tarafı
                kelly_frac = self.kelly_criterion(b_prob, market_implied, bot_config.strategy.kelly_fraction)
                recommended_side = "YES"
            else:
                # NO tarafı
                no_prob = 1 - b_prob
                no_implied = market.no_price or (1 - market_implied)
                no_edge = no_prob - no_implied

                if no_edge > 0:
                    kelly_frac = self.kelly_criterion(no_prob, no_implied, bot_config.strategy.kelly_fraction)
                    recommended_side = "NO"
                    raw_edge = no_edge
                else:
                    kelly_frac = 0
                    recommended_side = None

            # ── Slippage + fee adjusted edge ────────────────────────────
            # Net edge = raw edge − slippage − fee_drag.
            # This ensures the should_bet gate uses realistic post-cost
            # edge, not the raw theoretical edge that assumes perfect
            # fills at market price.
            entry_price_for_cost = (
                market_implied if recommended_side == "YES" else (market.no_price or (1 - market_implied))
            )

            # Extract condition_id from market.raw_data for orderbook slippage
            condition_id = None
            try:
                raw = json.loads(market.raw_data) if market.raw_data else {}
                for tok in raw.get("tokens", []):
                    if tok.get("outcome", "").upper() == (recommended_side or "").upper():
                        condition_id = tok.get("condition_id") or tok.get("token_id")
                        break
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

            # Preliminary bet amount for gas cost calculation (using raw edge)
            portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
            bankroll = portfolio.total_value if portfolio and portfolio.total_value else 1000.0
            # Conservative value (initial + realized PnL) for cap calculations.
            # max_bet_cap uses this as basis: conservative × MAX_EXPOSURE_PCT × max_bet_pct
            conservative = (portfolio.initial_value or 1000.0) + (portfolio.total_realized_pnl or 0.0)
            # EV FIX: Dinamik max_bet_pct ve kelly_fraction kullan.
            # Eski sabit %3 cap yüksek EV'yi sınırlıyordu.
            from utils.kelly import dynamic_max_bet_pct

            _dyn_pct = dynamic_max_bet_pct(raw_edge, Config.MAX_BET_PCT)
            prelim_kelly = min(kelly_frac * bankroll, max_bet_cap(conservative, _dyn_pct))

            net_edge = (
                adjust_edge_for_costs(raw_edge, entry_price_for_cost, bet_amount_usd=prelim_kelly)
                if recommended_side
                else 0.0
            )
            slippage_est = estimate_slippage(entry_price_for_cost, condition_id=condition_id)

            # ── Adjusted Edge (data-driven coefficients) ─────────────────────
            # Apply time, market type, side, RMSE, and spread penalties
            # Used as ADDITIONAL FILTER, not replacement for net_edge
            from engine.calculator import adjusted_edge

            ensemble_spread = std_val if std_val is not None else 0.0
            forecast_rmse = bot_config.strategy.forecast_rmse_by_horizon.get(min(days_ahead, 3), 1.5)

            adj_edge = adjusted_edge(
                raw_edge=raw_edge,
                days_ahead=days_ahead,
                market_type=market.metric,
                side=recommended_side,
                ensemble_spread=ensemble_spread,
                forecast_rmse=forecast_rmse,
            )

            # Bet miktarı — gerçek portföyden oku (using net_edge now)
            # EV FIX: Dinamik cap kullan — yüksek edge → yüksek cap.
            _dyn_pct_final = dynamic_max_bet_pct(raw_edge, Config.MAX_BET_PCT)
            raw_kelly_amount = min(kelly_frac * bankroll, max_bet_cap(conservative, _dyn_pct_final))
            # Reduce Kelly size by estimated slippage cost
            recommended_amount = adjust_kelly_for_slippage(raw_kelly_amount, entry_price_for_cost)

            # Bet açılmalı mı?
            # NOTE: Polymarket'te public-search'ten gelen marketlerin
            # `liquidity` alanı genelde 0 (price bize zaten gerçek bilgi veriyor),
            # bu yüzden likidite kontrolünü kaldırıyoruz — gerçek piyasa sinyali
            # `volume` veya `volume24hr` alanlarından biridir; bunlar da yoksa
            # `current_price` zaten likiditeyi yansıtır.
            # Yine de kullanıcı isterse `bot_config.strategy.min_liquidity`
            # değerini 0 yaparak bunu bypass edebilir.
            liquidity_ok = (
                market.liquidity or 0
            ) >= bot_config.strategy.min_liquidity or bot_config.strategy.min_liquidity <= 0
            effective_min_edge = self._compute_effective_min_edge(market, std_val)

            # ── Karpathy-search inefficiency gate ─────────────────────────
            # The "inefficiency" is the residual between our estimated
            # probability and the price-implied naive probability. In the
            # backtest harness this is the same construction (naive ensemble
            # average + independent noise). In the live system we don't
            # observe the inefficiency directly, but a good proxy is the
            # edge itself: an edge of `e` means the market is mispriced by
            # `e` in our favour. The Karpathy search found that requiring
            # `inefficiency_min` of -0.124 (i.e. accept even slightly
            # adverse inefficiency as long as other gates pass) gave the
            # best risk-adjusted return. We translate that to a *minimum
            # absolute edge* requirement on top of effective_min_edge.
            #
            # For a positive inefficiency_min (e.g. +0.067), we require the
            # edge to be at least that large. For negative values, the gate
            # is effectively disabled (we already require min_edge > 0).
            inefficiency_ok = abs(net_edge) >= inefficiency_min if inefficiency_min > 0 else True

            # Adjusted edge gate: additional filter (not replacement)
            adjusted_edge_ok = adj_edge >= effective_min_edge * 0.5  # 50% threshold

            should_bet = (
                net_edge >= effective_min_edge
                and inefficiency_ok
                and adjusted_edge_ok
                and len(forecast_values) >= bot_config.strategy.min_sources
                and bot_config.strategy.min_days_ahead <= days_ahead <= bot_config.strategy.max_days_ahead
                and liquidity_ok
                and recommended_amount > 1.0
            )

            reason_parts = []
            if net_edge < effective_min_edge:
                reason_parts.append(
                    f"Net edge düşük: {net_edge:.2%} (raw={raw_edge:.2%}, slip={slippage_est.slippage_pct:.2%})"
                )
            if not inefficiency_ok:
                reason_parts.append(f"İnefficiency düşük: edge {net_edge:.2%} < {inefficiency_min:.2%}")
            if len(forecast_values) < bot_config.strategy.min_sources:
                reason_parts.append(f"Az kaynak: {len(forecast_values)}")
            if days_ahead > bot_config.strategy.max_days_ahead:
                reason_parts.append(f"Çok uzak: {days_ahead} gün")
            if days_ahead < bot_config.strategy.min_days_ahead:
                reason_parts.append(f"Çok yakın: {days_ahead} gün (min={bot_config.strategy.min_days_ahead})")
            if (market.liquidity or 0) < bot_config.strategy.min_liquidity:
                reason_parts.append(f"Düşük likidite: ${market.liquidity}")

            if not reason_parts:
                reason = (
                    f"BET AC! Edge={net_edge:.2%} "
                    f"(raw={raw_edge:.2%}), "
                    f"Side={recommended_side}, "
                    f"slip={slippage_est.model_used}"
                )
            else:
                reason = "PASS: " + ", ".join(reason_parts)

            avg_val = sum(forecast_values) / len(forecast_values) if forecast_values else None

            analysis = Analysis(
                market_id=market_id,
                estimated_probability=estimated_prob,
                market_implied_prob=market_implied,
                edge=net_edge,
                raw_edge=raw_edge,
                adjusted_edge=adj_edge,
                slippage_pct=slippage_est.slippage_pct,
                avg_forecast_value=avg_val,
                std_forecast_value=std_val,
                num_sources=len(forecast_values),
                recommended_side=recommended_side,
                recommended_amount=recommended_amount,
                confidence_score=min(len(forecast_values) / 5, 1.0),
                should_bet=should_bet,
                reason=reason,
                model_predictions=model_predictions_json,
                analyzed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(analysis)
            logger.info(
                f"Market {market_id}: prob={estimated_prob:.2%}, "
                f"market={market_implied:.2%}, raw_edge={raw_edge:.2%}, "
                f"net_edge={net_edge:.2%} (slip={slippage_est.slippage_pct:.2%}), "
                f"should_bet={should_bet}, kelly_raw=${raw_kelly_amount:.2f}, kelly_adj=${recommended_amount:.2f}"
            )
            return analysis

    @staticmethod
    def _compute_effective_min_edge(market, std: float | None = None) -> float:
        """Time-to-close-scaled min_edge. Delegates to utils.probability."""
        return compute_effective_min_edge(market, std=std)


# WeatherEngine kept for seamless FastAPI / backward compatibility
OPEN_METEO_MODEL_MAP = {
    "gfs_seamless": "gfs_seamless",
    "ecmwf_ifs04": "ecmwf_ifs025",
    "gem_seamless": "gem_global",
    "icon_seamless": "icon_global",
    "jma_msm": "jma_seamless",
    "cma_grapes_global": "cma_grapes_global",
    "ukmo_seamless": "ukmo_seamless",
    "meteofrance_seamless": "meteofrance_seamless",
}

METRIC_MAP = {
    "temperature_max": "temperature_2m_max",
    "temperature_min": "temperature_2m_min",
    "temperature_2m_max": "temperature_2m_max",
    "temperature_2m_min": "temperature_2m_min",
}


class WeatherEngine:
    """Weather engine consensus calculator (FastAPI / test compatibility wrapper)."""

    def __init__(self, db_session_factory=None, cfg=None):
        self.db_session_factory = db_session_factory
        self.config = cfg or config
        # .copy() is required: get_normalized_weights() returns a direct
        # reference to bot_config.model_weights (the global singleton),
        # not a copy. Mutating it in place below would corrupt shared
        # config state across every other WeatherEngine/consumer.
        self.model_weights = dict(self.config.get_normalized_weights())

        # Overlay SIA-optimized weights persisted to data/model_weights.json.
        # Without this, the live betting engine silently ignores every
        # SIA weight update and stays frozen on the settings.py factory
        # defaults forever, even though SIALoop keeps optimizing and
        # writing to disk hourly. See SIALoop.__init__ for the same
        # load-and-overlay pattern (engine/strategy.py).
        persisted_weights = load_weights()
        if persisted_weights:
            for k, v in persisted_weights.items():
                if k in self.model_weights:
                    self.model_weights[k] = v
            logger.info(
                "WeatherEngine: SIA weights loaded from disk: %s",
                {k: round(v, 4) for k, v in self.model_weights.items()},
            )

        # Loaded once here (not per-forecast-call) since it reads
        # data/asi_calibration.json from disk; CalibrationEngine.__init__
        # caches the bias_map in memory for the lifetime of this instance.
        self._calibration = CalibrationEngine()

        # Local cache for the current session to avoid redundant fetches (e.g. max/min overlap)
        self._forecast_cache = {}
        # PER-5 FIX: Warm-start — bot baslarken DB'deki son forecast'leri
        # in-process cache'e yukle. Restart sonrasi ilk tarama hizlanir.
        self._warm_started = False

    def warm_start_from_db(self) -> int:
        """PER-5 FIX: Restart sonrasi in-process cache'i DB'den yukle.

        Bot baslarken cagrilmali. DB'deki son 3 gunun ensemble forecast'lerini
        okuyup (lat, lon) → forecast_data map'ini _forecast_cache'e yazar.

        Returns: yuklenen sehir sayisi.
        """
        if self._warm_started:
            return 0
        self._warm_started = True
        try:
            from database.db import get_session
            from database.models import WeatherForecast

            loaded = 0
            with get_session() as session:
                from datetime import timedelta

                cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
                rows = (
                    session.query(WeatherForecast)
                    .filter(WeatherForecast.fetched_at >= cutoff)
                    .filter(WeatherForecast.source.in_(self.model_weights.keys()))
                    .all()
                )
                city_models: dict[tuple, dict[str, float]] = {}
                for r in rows:
                    key = (round(r.lat or 0, 4), round(r.lon or 0, 4))
                    city_models.setdefault(key, {})[r.source] = float(r.predicted_value or 0)

                for key, model_temps_db in city_models.items():
                    if len(model_temps_db) < 3:
                        continue
                    total_weight = sum(self.model_weights.get(m, 0.0) for m in model_temps_db)
                    if total_weight <= 0:
                        continue
                    weighted_mean = (
                        sum(self.model_weights.get(m, 0.0) * t for m, t in model_temps_db.items()) / total_weight
                    )
                    weighted_var = (
                        sum(
                            self.model_weights.get(m, 0.0) * (t - weighted_mean) ** 2 for m, t in model_temps_db.items()
                        )
                        / total_weight
                    )
                    weighted_std = max(weighted_var**0.5, 0.5)
                    self._forecast_cache[key] = {
                        "weighted_mean": weighted_mean,
                        "weighted_std": weighted_std,
                        "model_count": len(model_temps_db),
                        "model_temps": model_temps_db,
                        "timestamp": datetime.now(UTC).replace(tzinfo=None),
                    }
                    loaded += 1
            if loaded > 0:
                logger.info("PER-5 warm-start: %d sehir DB'den in-process cache'e yuklendi", loaded)
            return loaded
        except Exception as e:
            logger.warning("PER-5 warm-start failed: %s", e)
            return 0

    @staticmethod
    def _compute_effective_min_edge(market, std: float | None = None) -> float:
        """Return the time-to-close-scaled min_edge. Delegates to utils.probability."""
        return compute_effective_min_edge(market, std=std)

    async def get_multi_model_forecast(
        self,
        city_code: str,
        latitude: float,
        longitude: float,
        target_date: datetime | None = None,
        market_ids: list[str] = None,
        db_session=None,
        metric: str = "temperature_2m_max",
        aiohttp_session=None,
    ) -> dict | None:
        """Fetch multi-model ensemble forecast for a city.

        Optional aiohttp_session: reuse an external session to avoid
        creating a new TCP+TLS connection per city (big performance win
        when fetching 65+ cities sequentially).
        """
        if not city_code or (latitude == 0 and longitude == 0):
            return None
        if target_date is None:
            target_date = datetime.now(UTC).replace(tzinfo=None)

        api_model_names = []
        for internal_name in self.model_weights:
            api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
            if api_name not in api_model_names:
                api_model_names.append(api_name)
        models_str = ",".join(api_model_names)

        # Cache check: key by (lat, lon) only — the API already returns 14 days
        # of data per call, so one call per city covers ALL open-market dates.
        target_str = target_date.strftime("%Y-%m-%d")
        city_cache_key = (round(latitude, 4), round(longitude, 4))
        data = self._forecast_cache.get(city_cache_key)
        # Verify cached data covers the target_date (avoid stale if days pass)
        if data is not None:
            cached_times = data.get("daily", {}).get("time", [])
            if target_str not in cached_times:
                data = None  # date outside range — refetch

        if data is not None:
            logger.debug("Ensemble cache hit for city %s (date %s)", city_cache_key, target_str)
        else:
            # DB cache: check if we already have ensemble forecasts for this city
            # from a previous run. This avoids re-fetching all cities on restart.
            if db_session is not None:
                try:
                    from database.models import WeatherForecast

                    existing = (
                        db_session.query(WeatherForecast)
                        .filter(
                            WeatherForecast.lat == latitude,
                            WeatherForecast.lon == longitude,
                            WeatherForecast.target_date == target_date,
                            WeatherForecast.metric == metric,
                            WeatherForecast.source.in_(self.model_weights.keys()),
                        )
                        .all()
                    )
                    if existing and len(existing) >= 3:
                        # Reconstruct ensemble from DB forecasts
                        model_temps_db: dict[str, float] = {}
                        for fe in existing:
                            if fe.source not in model_temps_db:
                                model_temps_db[fe.source] = fe.predicted_value

                        # Verify we have enough models
                        if len(model_temps_db) >= 3:
                            total_weight = sum(self.model_weights.get(m, 0.0) for m in model_temps_db)
                            if total_weight > 0:
                                weighted_mean = (
                                    sum(self.model_weights.get(m, 0.0) * t for m, t in model_temps_db.items())
                                    / total_weight
                                )
                                weighted_var = (
                                    sum(
                                        self.model_weights.get(m, 0.0) * (t - weighted_mean) ** 2
                                        for m, t in model_temps_db.items()
                                    )
                                    / total_weight
                                )
                                weighted_std = max(weighted_var**0.5, 0.5)

                                logger.info(
                                    "DB cache hit for %s (date %s): %d models, mean=%.1f",
                                    city_cache_key,
                                    target_str,
                                    len(model_temps_db),
                                    weighted_mean,
                                )
                                return {
                                    "weighted_mean": weighted_mean,
                                    "weighted_std": weighted_std,
                                    "model_count": len(model_temps_db),
                                    "model_temps": model_temps_db,
                                    "timestamp": existing[0].fetched_at,
                                }
                except Exception as e:
                    logger.debug("DB cache check failed for %s: %s", city_cache_key, e)

            url = f"{Config.OPEN_METEO_API}/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "models": models_str,
                # Open-Meteo supports up to 16 days forecast
                "forecast_days": 16,
            }

            try:
                # BUG-3 FIX: Use global 429 cooldown instead of per-city
                # exponential backoff (30s→60s→120s). One 429 cools down
                # the entire batch for 30s, then all cities resume.
                # Max 2 retries with 15s wait = worst case 30s per city.
                global _global_429_until
                max_retries = 2
                data = None
                for attempt in range(max_retries + 1):
                    # Check global cooldown before making request
                    now = time.monotonic()
                    if now < _global_429_until:
                        cooldown_left = _global_429_until - now
                        logger.info(
                            "Ensemble API: global 429 cooldown active, waiting %.0fs for %s",
                            cooldown_left,
                            city_cache_key,
                        )
                        await asyncio.sleep(cooldown_left)

                    try:
                        if aiohttp_session is not None:
                            async with aiohttp_session.get(
                                url,
                                params=params,
                                timeout=aiohttp.ClientTimeout(total=30),
                            ) as resp:
                                if resp.status == 429:
                                    if attempt < max_retries:
                                        retry_after = resp.headers.get("Retry-After")
                                        wait = min(float(retry_after) if retry_after else _GLOBAL_429_COOLDOWN_S, 30.0)
                                        logger.warning(
                                            "Ensemble API 429 (attempt %d/%d) — global cooldown %.0fs for %s",
                                            attempt + 1,
                                            max_retries + 1,
                                            wait,
                                            city_cache_key,
                                        )
                                        _global_429_until = time.monotonic() + wait
                                        await asyncio.sleep(wait)
                                        continue
                                    logger.error(
                                        "Ensemble API 429 after %d retries — giving up for %s",
                                        max_retries,
                                        city_cache_key,
                                    )
                                    return None
                                if resp.status != 200:
                                    logger.warning("Ensemble API status %d for %s", resp.status, city_cache_key)
                                    return None
                                data = await resp.json()
                        else:
                            async with aiohttp.ClientSession() as session, session.get(
                                url,
                                params=params,
                                timeout=aiohttp.ClientTimeout(total=30),
                            ) as resp:
                                if resp.status == 429:
                                    if attempt < max_retries:
                                        retry_after = resp.headers.get("Retry-After")
                                        wait = min(
                                            float(retry_after) if retry_after else _GLOBAL_429_COOLDOWN_S, 30.0
                                        )
                                        logger.warning(
                                            "Ensemble API 429 (attempt %d/%d) — global cooldown %.0fs for %s",
                                            attempt + 1,
                                            max_retries + 1,
                                            wait,
                                            city_cache_key,
                                        )
                                        _global_429_until = time.monotonic() + wait
                                        await asyncio.sleep(wait)
                                        continue
                                    logger.error(
                                        "Ensemble API 429 after %d retries — giving up for %s",
                                        max_retries,
                                        city_cache_key,
                                    )
                                    return None
                                if resp.status != 200:
                                    logger.warning("Ensemble API status %d for %s", resp.status, city_cache_key)
                                    return None
                                data = await resp.json()
                        # Success — break out of retry loop
                        if data is not None:
                            break
                    except TimeoutError:
                        if attempt < max_retries:
                            logger.warning(
                                "Ensemble API timeout (attempt %d/%d) — retrying in 15s for %s",
                                attempt + 1,
                                max_retries + 1,
                                city_cache_key,
                            )
                            await asyncio.sleep(15)
                            continue
                        logger.error("Ensemble API timeout after %d retries for %s", max_retries, city_cache_key)
                        return None

                if data is None:
                    return None
                self._forecast_cache[city_cache_key] = data
            except Exception as e:
                logger.error("get_multi_model_forecast fetch error: %s", e)
                return None

        try:
            model_temps = {}
            daily_data = data.get("daily", {})
            times = daily_data.get("time", [])
            if not times:
                return None

            target_idx = None
            for i, t in enumerate(times):
                if t.startswith(target_str):
                    target_idx = i
                    break

            # Timezone robustness fix: Open-Meteo with `timezone=auto` returns
            # daily buckets in *local* time. For cities east of UTC (e.g. Seoul
            # at UTC+9), the local "today" can be one day ahead of UTC "today",
            # so the UTC target_str is not in the response. Similarly, cities
            # west of UTC (e.g. Los Angeles at UTC-8) can return a date that
            # is one day *behind* UTC today for the first bucket.
            #
            # Strategy: if exact match not found, fall back to the bucket whose
            # calendar date is closest to the target_date (within ±1 day). This
            # matches what the Polymarket market question means by "today" —
            # the local calendar day at the city, not UTC.
            if target_idx is None:
                try:
                    target_d = target_date.date()
                    best_idx = None
                    best_delta = None
                    for i, t in enumerate(times):
                        try:
                            d = datetime.strptime(t, "%Y-%m-%d").date()
                        except ValueError:
                            continue
                        delta = abs((d - target_d).days)
                        if best_delta is None or delta < best_delta:
                            best_delta = delta
                            best_idx = i
                    # Only accept the closest match if it is within 1 day,
                    # otherwise the lookup is genuinely stale and we should
                    # return None to avoid silently returning wrong-day data.
                    if best_idx is not None and best_delta is not None and best_delta <= 1:
                        target_idx = best_idx
                        logger.info(
                            "Timezone fallback: target=%s not in API response; using closest bucket %s (delta=%d day)",
                            target_str,
                            times[target_idx],
                            best_delta,
                        )
                except Exception as e:
                    logger.debug("Timezone fallback failed: %s", e)

            if target_idx is None:
                logger.warning(
                    "get_multi_model_forecast: target_date=%s not found in API dates %s",
                    target_str,
                    times[:5],
                )
                return None

            # FIX (S6): Fetch BOTH max and min metrics in one API call.
            # Previously, this code only extracted the *requested* metric, so a
            # city with both temperature_max and temperature_min markets would
            # trigger two API calls (double the rate-limit pressure). Now we
            # extract both, save both to DB, but only return the requested one
            # in model_temps (so the consensus calculation stays correct).
            model_temps: dict[str, float] = {}  # requested metric only
            # {"temperature_max": {model: temp}, "temperature_min": {...}}
            side_metrics: dict[str, dict[str, float]] = {}

            for internal_name in self.model_weights:
                api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
                for api_metric, metric_label in [
                    ("temperature_2m_max", "temperature_max"),
                    ("temperature_2m_min", "temperature_min"),
                ]:
                    key = f"{api_metric}_{api_name}"
                    if key not in daily_data:
                        continue
                    temps = daily_data[key]
                    if target_idx >= len(temps) or temps[target_idx] is None:
                        continue
                    raw_temp = temps[target_idx]
                    # Apply the systematic per-model bias correction (MBE)
                    # computed by CalibrationEngine from historical settled markets.
                    calibrated_temp = self._calibration.get_calibrated_temperature(
                        city_code, metric_label, internal_name, raw_temp
                    )
                    side_metrics.setdefault(metric_label, {})[internal_name] = calibrated_temp
                    # Only populate model_temps with the REQUESTED metric so the
                    # consensus/return value is for the right metric.
                    if metric_label == metric:
                        model_temps[internal_name] = calibrated_temp

            if not model_temps:
                return None

            # Calculate consensus
            total_weight = sum(self.model_weights.get(m, 0.0) for m in model_temps)
            if total_weight == 0:
                return None
            weighted_mean = sum(self.model_weights.get(m, 0.0) * t for m, t in model_temps.items()) / total_weight
            weighted_var = (
                sum(self.model_weights.get(m, 0.0) * (t - weighted_mean) ** 2 for m, t in model_temps.items())
                / total_weight
            )
            weighted_std = max(weighted_var**0.5, 0.5)

            if db_session is not None and market_ids:
                from database.models import WeatherForecast

                # FIX (S6): Persist BOTH metrics to DB so the next market for
                # the same (city, date) but different metric gets a cache hit
                # instead of triggering another API call.
                for mid in market_ids:
                    for metric_label, per_model_temps in side_metrics.items():
                        # Skip if this metric isn't requested by any of the
                        # passed market_ids — but we don't know per-market
                        # metric here, so persist both. The DB row's `metric`
                        # column ensures analyzer queries the right one.
                        for mn, tmp in per_model_temps.items():
                            db_session.add(
                                WeatherForecast(
                                    market_id=mid,
                                    city=city_code,
                                    lat=latitude,
                                    lon=longitude,
                                    target_date=target_date,
                                    metric=metric_label,  # FIX: was `metric` (only requested), now both
                                    source=mn,
                                    predicted_value=float(tmp),
                                    model_weight=self.model_weights.get(mn, 0.0),
                                    fetched_at=datetime.now(UTC).replace(tzinfo=None),
                                    raw_data=str({"model": mn, "temp": tmp, "ensemble": True, "metric": metric_label}),
                                )
                            )
                try:
                    db_session.commit()
                    logger.info(
                        "Ensemble persisted for %d markets × %d metrics, coords=(%s, %s)",
                        len(market_ids),
                        len(side_metrics),
                        latitude,
                        longitude,
                    )
                except Exception as e:
                    db_session.rollback()
                    logger.error("Failed to persist ensemble: %s", e)

            return {
                "weighted_mean": weighted_mean,
                "weighted_std": weighted_std,
                "model_count": len(model_temps),
                "model_temps": model_temps,
                # CRITICAL FIX (metric mismatch): return BOTH max and min side_metrics
                # so the caller (_persist_ensemble in meteo.py) can persist forecasts
                # for both metrics. Previously only the requested metric was returned,
                # so temperature_min markets got temperature_max forecasts saved
                # under their market_id — causing the analyzer to see 0 matching
                # forecasts and reject every temperature_min bet.
                "side_metrics": side_metrics,
                "requested_metric": metric,
                "timestamp": datetime.now(UTC).replace(tzinfo=None),
            }
        except Exception as e:
            logger.error("get_multi_model_forecast error: %s", e)
            return None

    def _db_consensus(self, market_id: str) -> dict | None:
        if not market_id or not self.db_session_factory:
            return None
        db = self.db_session_factory()
        try:
            from database.models import WeatherForecast

            fcs = (
                db.query(WeatherForecast)
                .filter(WeatherForecast.market_id == market_id)
                .order_by(WeatherForecast.fetched_at.desc())
                .limit(30)
                .all()
            )
            if not fcs:
                return None
            lat = {}
            for f in fcs:
                if f.source not in lat:
                    lat[f.source] = (
                        f.predicted_value,
                        self.model_weights.get(f.source, 0.0),
                    )
            tw = sum(w for _, w in lat.values())
            if tw <= 0:
                vs = [v for v, _ in lat.values()]
                m = sum(vs) / len(vs)
                s = max((sum((v - m) ** 2 for v in vs) / len(vs)) ** 0.5, 0.5) if len(vs) > 1 else 1.0
                return {"weighted_mean": m, "weighted_std": s}
            wm = sum(v * w for v, w in lat.values()) / tw
            wv = sum(w * (v - wm) ** 2 for v, w in lat.values()) / tw
            return {"weighted_mean": wm, "weighted_std": max(wv**0.5, 0.5)}
        except Exception:
            return None
        finally:
            db.close()

    def calculate_probability_above(self, strike_temp: float, consensus=None, market_id=""):
        """P(YES) for a HIGH market — delegates to shared estimate_probability."""
        if not consensus:
            consensus = self._db_consensus(market_id)
        if not consensus:
            return 0.5
        return _estimate_probability(
            mean=consensus["weighted_mean"],
            std=consensus["weighted_std"],
            threshold=strike_temp,
            days_ahead=0,
            market_type="HIGH",
        )

    def calculate_probability_below(self, strike_temp: float, consensus=None, market_id=""):
        """P(YES) for a LOW market — delegates to shared estimate_probability."""
        if not consensus:
            consensus = self._db_consensus(market_id)
        if not consensus:
            return 0.5
        return _estimate_probability(
            mean=consensus["weighted_mean"],
            std=consensus["weighted_std"],
            threshold=strike_temp,
            days_ahead=0,
            market_type="LOW",
        )

    async def get_forecast(
        self,
        city_code: str,
        latitude: float,
        longitude: float,
        target_date: datetime | None = None,
    ) -> dict | None:
        return await self.get_multi_model_forecast(city_code, latitude, longitude, target_date)

    def update_model_weights(self, new_weights: dict):
        self.model_weights = new_weights
