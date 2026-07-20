"""Sinyal analizi, Kelly kasa yönetimi, risk kontrolü ve SIA (Self-Improving Algorithm)."""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from config.settings import bot_config, config
from database.models import (
    OPEN_BET_STATUSES,
    Analysis,
    Bet,
    ModelPerformance,
    Portfolio,
    WeatherMarket,
)
from utils.formulas import conservative_portfolio_value, max_exposure_cap
from utils.adaptive_sizing import get_kelly_fraction
from utils.kelly import kelly_bet_amount
from utils.weights_store import (
    load_strategy_params,
    load_weights,
    save_strategy_params,
    save_weights,
)

logger = logging.getLogger("STRATEGY_ENGINE")


class SimpleSignal:
    """Lightweight signal object for inter-module compatibility."""

    market_id: str = ""
    city: str = ""
    city_code: str = ""
    outcome: str = "YES"
    entry_price: float = 0.5
    fair_value: float = 0.5
    edge: float = 0.0
    probability: float = 0.5
    bet_size: float = 0.0
    ladder_orders: list = None  # type: ignore[assignment]
    side: str = "YES"

    def __init__(self, **kwargs):
        self.ladder_orders = []
        for k, v in kwargs.items():
            setattr(self, k, v)


class RiskManager:
    """Risk management with Kelly sizing and circuit breakers."""

    def __init__(self, db_session=None, cfg=None):
        self.db = db_session
        self.config = cfg or config
        self.portfolio_value = getattr(self.config, "INITIAL_PORTFOLIO", 1000.0)
        self.daily_pnl = 0.0
        # Load current portfolio value from DB so exposure cap uses
        # the actual portfolio, not just INITIAL_PORTFOLIO.
        self._load_portfolio_from_db()
        self.open_bets_count = 0
        # Drawdown high-water-mark monitor: de-risks automatically as the
        # bankroll falls from its peak (green/yellow/red/critical tiers).
        from utils.drawdown_monitor import DrawdownMonitor

        self.drawdown = DrawdownMonitor()
        self.city_bet_counts: dict[str, int] = {}
        self._last_pnl_date: datetime | None = None
        self._load_from_db()

    def _load_portfolio_from_db(self):
        """Load current portfolio total_value from DB."""
        if not self.db:
            return
        try:
            from database.models import Portfolio

            p = self.db.query(Portfolio).filter(Portfolio.id == 1).first()
            if p and p.total_value:
                self.portfolio_value = float(p.total_value)
        except Exception as e:
            logger.warning("portfolio load fallback: %s", e)

    def update_portfolio(self, value: float):
        """Update portfolio value."""
        self.portfolio_value = value

    def update_daily_pnl(self, pnl: float):
        """Update daily PnL and check circuit breaker."""
        now = datetime.now(timezone.utc)
        if self._last_pnl_date is None or self._last_pnl_date.date() != now.date():
            if self._last_pnl_date is not None:
                logger.info("Daily PnL reset for new day (was $%.2f)", self.daily_pnl)
            self.daily_pnl = 0.0
            self._last_pnl_date = now
        self.daily_pnl += pnl
        if self.daily_pnl <= -self.daily_loss_limit_amount:
            logger.warning("DAILY STOP-LOSS TRIGGERED! PnL: $%.2f", self.daily_pnl)
            return False
        return True

    def check_city_cap(self, city_code: str) -> bool:
        """Check city cap limit."""
        current_count = self.city_bet_counts.get(city_code, 0)
        return current_count < self.config.CITY_CAP

    def increment_city_bet(self, city_code: str):
        """Increment city bet count."""
        self.city_bet_counts[city_code] = self.city_bet_counts.get(city_code, 0) + 1

    def decrement_city_bet(self, city_code: str):
        """Decrement city bet count."""
        if city_code in self.city_bet_counts:
            self.city_bet_counts[city_code] = max(0, self.city_bet_counts[city_code] - 1)

    def calculate_kelly_bet_size(self, model_prob: float, market_price: float) -> float:
        """Calculate Kelly bet sizing.

        Thin wrapper over utils.kelly.kelly_bet_amount so the math
        lives in one place. Bankroll comes from self.portfolio_value,
        which the portfolio-sync hook refreshes after every settlement
        cycle (PR #9).
        """
        return kelly_bet_amount(
            self.portfolio_value,
            model_prob,
            market_price,
            fraction=get_kelly_fraction(),
            min_bet=self.config.MIN_BET_SIZE,
            max_bet_pct=self.config.MAX_BET_PCT,
        )

    def check_exposure_cap(self, current_exposure: float, additional_bet: float) -> bool:
        """Check total exposure cap limit.

        Portfolio = initial_capital + realized_pnl (unrealized katilmaz).
        Limit = portfolio * 25%. Her gun PnL sermayeye eklenir.
        """
        conservative_value = self._conservative_portfolio_value()
        max_exposure = max_exposure_cap(
            self.config.INITIAL_PORTFOLIO,
            conservative_value - self.config.INITIAL_PORTFOLIO,
            self.config.TOTAL_EXPOSURE_PCT,
        )
        if (current_exposure + additional_bet) > max_exposure:
            logger.warning(
                "Exposure cap: $%.2f + $%.2f = $%.2f > $%.2f (25%% of $%.2f conservative)",
                current_exposure,
                additional_bet,
                current_exposure + additional_bet,
                max_exposure,
                conservative_value,
            )
            return False
        return True

    def _conservative_portfolio_value(self) -> float:
        """Portfolio = dünkü kapanış sermayesi (bugünkü realize edilmemiş).

        Bugünden önce kapanan bahislerin PnL'i hesaba katılır.
        Bugün realizado olan kârlar bugünkü exposure cap'ini şişirmez.
        Yarınki başlangıç = bugünkü kapanış.

        Bu sayede:
        - Daily starting capital = önceki günün kapanış sermayesi
        - Max exposure = %25 × dünkü kapanış
        - Feedback loop önlenir (unrealized PnL dahil edilmez)

        Formula from: utils/formulas.py → conservative_portfolio_value()
        """
        if not self.db:
            return self.portfolio_value
        try:
            from datetime import datetime, timezone

            from sqlalchemy import or_

            from database.models import Bet

            initial = self.config.INITIAL_PORTFOLIO
            # Sadece BUGÜNDEN ÖNCE kapanan bahislerin PnL'i
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            realized = float(
                self.db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
                .filter(
                    Bet.status.in_(("won", "lost", "settled", "closed_early")),
                    or_(
                        Bet.settled_at < today_start,
                        Bet.closed_at < today_start,
                    ),
                )
                .scalar()
                or 0.0
            )
            # Use central formula
            return conservative_portfolio_value(initial, realized)
        except Exception as e:
            logger.warning("conservative_portfolio fallback: %s", e)
            return self.portfolio_value

    @property
    def daily_loss_limit_amount(self) -> float:
        """Günlük zarar limiti = dünkü kapanış sermayesi × DAILY_LOSS_LIMIT."""
        return self._conservative_portfolio_value() * self.config.DAILY_LOSS_LIMIT

    def is_bot_locked(self) -> bool:
        """Check if bot is locked."""
        return self.daily_pnl <= -self.daily_loss_limit_amount

    def get_daily_pnl(self) -> float:
        """Get daily PnL."""
        return self.daily_pnl

    def get_total_exposure(self) -> float:
        """Get total exposure (sum of `amount` for all open/active/placed bets)."""
        if self.db:
            try:
                # Include all open-style statuses so freshly-placed bets are
                # counted in exposure. "placed" is what BetPlacer writes
                # immediately after writing the Bet row. Use `Bet.amount`
                # (the column BetPlacer actually writes) rather than the
                # legacy `stake_amount` which stays at 0.
                total = self.db.query(func.coalesce(func.sum(Bet.amount), 0.0)).filter(Bet.status.in_(OPEN_BET_STATUSES)).scalar()
                return float(total or 0.0)
            except Exception:
                pass
        exposure = sum(self.city_bet_counts.values()) * 20.0
        return exposure

    def get_portfolio_value(self) -> float:
        """Get portfolio value."""
        return self.portfolio_value

    def _load_from_db(self):
        """Load state from DB."""
        if not self.db:
            return
        try:
            portfolio = self.db.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                self.portfolio_value = portfolio.total_value or portfolio.initial_value or self.portfolio_value
                self.daily_pnl = portfolio.daily_pnl or 0.0

            active = self.db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()
            self.city_bet_counts = {}
            self.open_bets_count = len(active)
            for bet in active:
                cc = bet.city_code or "unknown"
                self.city_bet_counts[cc] = self.city_bet_counts.get(cc, 0) + 1
        except Exception as e:
            logger.warning("Risk load from DB warning: %s", e)

    # ──────────────────────────────────────────────
    # Active Risk Management — Position-Level Methods
    # ──────────────────────────────────────────────
    # These methods evaluate individual positions for early exit (stop-loss,
    # take-profit, time decay, trailing stop) and portfolio rebalancing.
    #
    # risk_config comes from bot_config.risk (RiskConfig dataclass in settings.py)

    def _get_risk_config(self):
        """Return risk config with fallback defaults."""
        try:
            from config.settings import bot_config

            return bot_config.risk
        except Exception:
            from config.settings import RiskConfig

            return RiskConfig()

    def check_stop_loss(self, bet, current_price: float, market=None) -> tuple:  # pylint: disable=unused-argument
        """Stop-loss: pozisyon %stop_loss_pct'den fazla zarardaysa kapat."""
        from utils.formulas import pnl_ratio

        cfg = self._get_risk_config()
        raw = bet.entry_price if bet.entry_price is not None else bet.price
        entry = float(raw) if raw is not None else 0.0
        if entry <= 0:
            return False, ""
        ratio = pnl_ratio(current_price, entry)
        if ratio <= -cfg.stop_loss_pct:
            return True, f"stop_loss: {ratio:.1%}"
        return False, ""

    def check_take_profit(self, bet, current_price: float, market=None) -> tuple:  # pylint: disable=unused-argument
        """Take-profit: pozisyon %take_profit_pct'den fazla kardaysa veya fiyat 0.98'e ulaştıysa kapat.

        Partial take-profit: düşük girişli ("lottery ticket") bahislerde,
        ~%100 kârda sadece ana parayı kurtaracak kadar satılır, kalan pozisyon
        trailing stop ile "free ride" devam eder. (Bizim RiskConfig flat'tır;
        spec'teki tier sistemi YOK — sadece entry fiyatı + kâr ile tetiklenir.)
        Bu fonksiyon SADECE karar verir; pozisyon küçültme + muhasebe
        scheduler._partial_close_early içinde yapılır (çift mutasyon yok).
        """
        from utils.formulas import pnl_ratio

        cfg = self._get_risk_config()
        raw = bet.entry_price if bet.entry_price is not None else bet.price
        entry = float(raw) if raw is not None else 0.0
        if entry <= 0:
            return False, ""

        # Fiyat 0.98'e ulaştı → kesin kazanç, hemen TAM kapat (partial değil)
        if current_price >= 0.98:
            return True, f"near_certain_win: price={current_price:.2f}"

        # Partial TP: zaten yapıldıysa tekrar tetikleme (trailing stop'a bırak)
        if bool(getattr(bet, "partial_tp_done", False)):
            return False, ""

        # Partial TP: düşük giriş (<=0.35) ve ~%100 kâr
        if entry <= 0.35 and current_price > 0:
            profit_pct = (current_price - entry) / entry
            if profit_pct >= 1.0:
                fraction_to_sell = entry / current_price
                if 0 < fraction_to_sell < 1:
                    # Karar yeterli; scheduler pozisyonu küçültür.
                    return (
                        True,
                        f"partial_take_profit: sold {fraction_to_sell:.1%} @ {current_price:.2f}",
                    )

        # Normal (tam) take-profit
        ratio = pnl_ratio(current_price, entry)
        if ratio >= cfg.take_profit_pct:
            return True, f"take_profit: {ratio:.1%}"
        return False, ""

    def check_time_decay(self, bet, current_price: float, market) -> tuple:
        """Time decay: settlement'a <time_decay_hours kala ve zarardaysa kapat."""
        from utils.formulas import pnl_ratio

        cfg = self._get_risk_config()
        if not market or not hasattr(market, "target_date"):
            return False, ""
        try:
            resolution = market.target_date
            if not resolution:
                return False, ""
            # Naive datetime'leri timezone-aware yap
            if resolution.tzinfo is None:
                resolution = resolution.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_left = (resolution - now).total_seconds() / 3600
            if hours_left <= 0:
                return False, ""  # Zaten geçmiş, settlement halleder
            if hours_left <= cfg.time_decay_hours:
                raw = bet.entry_price if bet.entry_price is not None else bet.price
                entry = float(raw) if raw is not None else 0.0
                if entry > 0:
                    ratio = pnl_ratio(current_price, entry)
                    if ratio <= cfg.time_decay_threshold:
                        return (
                            True,
                            f"time_decay: {hours_left:.1f}h left, {ratio:.1%}",
                        )
        except Exception:
            pass
        return False, ""

    def check_trailing_stop(self, bet, current_price: float) -> tuple:
        """Trailing stop: en yüksek fiyattan %trailing_stop_pct düşüşte kapat.

        Sadece pozisyon kâra geçmişse (peak > entry) tetiklenir.
        Peak <= entry ise pozisyon hiç kâra geçmemiş, TS koruma sağlamaz.
        """
        from utils.formulas import drop_ratio

        cfg = self._get_risk_config()
        raw = bet.entry_price if bet.entry_price is not None else bet.price
        entry = float(raw) if raw is not None else 0.0
        if entry <= 0:
            return False, ""

        # Peak price'ı result_data'dan oku veya ilk defa set et
        peak = entry
        if bet.result_data:
            try:
                data = json.loads(bet.result_data) if isinstance(bet.result_data, str) else {}
                peak = float(data.get("peak_price", entry))
            except Exception:
                peak = entry

        # Yeni tepe noktası var mı?
        if current_price > peak:
            peak = current_price
            # Güncellenmiş peak değerini kaydet
            try:
                data = json.loads(bet.result_data) if isinstance(bet.result_data, str) else {}
                if not isinstance(data, dict):
                    data = {}
                data["peak_price"] = peak
                bet.result_data = json.dumps(data)
            except Exception:
                pass

        # Sadece pozisyon kâra geçmişse (peak > entry) TS uygula
        # Peak <= entry ise pozisyon hiç kâra geçmemiş, TS tetiklenmesin
        if peak <= entry:
            return False, ""

        # Tepeden düşüş kontrolü
        if peak > 0:
            ratio = drop_ratio(peak, current_price)
            if ratio >= cfg.trailing_stop_pct:
                return (
                    True,
                    f"trailing_stop: dropped {ratio:.1%} from peak {peak:.3f}",
                )

        return False, ""

    def check_early_exit(self, bet, current_price: float, market=None) -> tuple:
        """Tüm erken çıkış kontrollerini sırayla çalıştır.

        Returns: (should_exit: bool, reason: str)
        """
        # Minimum hold: bet aynı scan döngüsünde açıldıysa kapatma.
        # Bu, resolve edilmiş market'lere anında bet açılıp kapanmasını engeller.
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        placed = getattr(bet, "placed_at", None)
        if placed:
            if placed.tzinfo is None:
                placed = placed.replace(tzinfo=timezone.utc)
            hold_seconds = (now - placed).total_seconds()
            if hold_seconds < 180:  # 3 dakika minimum hold
                return False, "Hold (minimum hold period)"

        # 1. Stop-loss
        exit_bool, reason = self.check_stop_loss(bet, current_price, market)
        if exit_bool:
            return True, reason

        # 2. Take-profit
        exit_bool, reason = self.check_take_profit(bet, current_price, market)
        if exit_bool:
            return True, reason

        # 3. Trailing stop
        exit_bool, reason = self.check_trailing_stop(bet, current_price)
        if exit_bool:
            return True, reason

        # 4. Time decay (sadece market objesi varsa)
        if market is not None:
            exit_bool, reason = self.check_time_decay(bet, current_price, market)
            if exit_bool:
                return True, reason

        return False, "Hold"

    def check_model_reversal(self, bet, analysis) -> tuple:
        """Model olasılığı ters yönde önemli ölçüde değiştiyse erken çık.

        Returns: (should_exit: bool, reason: str)
        """
        if not analysis:
            return False, ""
        try:
            # Bet'in açıldığı andaki model prob'u fair_value'da saklı
            entry_prob = float(getattr(bet, "fair_value", 0.5) or 0.5)
            current_prob = float(getattr(analysis, "estimated_probability", 0.5) or 0.5)

            if entry_prob <= 0 or current_prob <= 0:
                return False, ""

            prob_change = current_prob - entry_prob
            bet_pnl = float(getattr(bet, "unrealized_pnl", 0) or 0)
            bet_stake = float(getattr(bet, "stake", bet.amount or 1))
            return_pct = bet_pnl / bet_stake if bet_stake > 0 else 0

            # Model prob'u %20+ ters yönde değiştiyse ve zarardaysak çık
            if prob_change <= -0.20 and return_pct <= -0.10:
                return (
                    True,
                    f"model_reversal: prob {entry_prob:.0%}->{current_prob:.0%} ({prob_change:.0%})",
                )

            # Model prob'u %30+ ters yönde değiştiyse (karda da olsak çık)
            if prob_change <= -0.30:
                return (
                    True,
                    f"model_reversal: prob {entry_prob:.0%}->{current_prob:.0%} ({prob_change:.0%})",
                )

        except Exception:
            pass
        return False, ""


class SIALoop:
    """Self-Improving Algorithm loop using Brier Score optimization."""

    def __init__(self, db_session_factory=None, cfg=None):
        self.db_session_factory = db_session_factory
        self.config = cfg or config
        self.model_weights = self.config.MODEL_WEIGHTS.copy()

        # Load persisted weights
        persisted_weights = load_weights()
        if persisted_weights:
            for k, v in persisted_weights.items():
                if k in self.model_weights:
                    self.model_weights[k] = v
            logger.info(
                "SIA weights loaded from disk: %s",
                {k: round(v, 4) for k, v in self.model_weights.items()},
            )

        # Load persisted strategy parameters
        persisted_strategy = load_strategy_params()
        if persisted_strategy:
            strategy = bot_config.strategy
            if "min_edge" in persisted_strategy:
                strategy.min_edge = float(persisted_strategy["min_edge"])
            if "kelly_fraction" in persisted_strategy:
                strategy.kelly_fraction = float(persisted_strategy["kelly_fraction"])
            logger.info("SIA strategy parameters loaded from disk: %s", persisted_strategy)

    def calculate_brier_score(self, predictions: list[float], outcomes: list[bool]) -> float:
        """Calculate Brier Score."""
        if len(predictions) != len(outcomes) or len(predictions) == 0:
            return 1.0

        squared_errors = [(pred - (1.0 if outcome else 0.0)) ** 2 for pred, outcome in zip(predictions, outcomes)]
        brier_score = sum(squared_errors) / len(squared_errors)
        return round(brier_score, 4)

    def analyze_model_performance(self, days: int = 30) -> dict[str, dict]:
        """Analyze performance of each model over recent settled bets.

        For each settled bet, fetches the associated Analysis record containing
        per-model probability predictions (``model_predictions`` JSON).  The
        YES/NO outcome is determined from the **market resolution data**
        (``raw_data`` JSON → ``outcome`` field), ensuring that Brier is always
        computed against P(YES) regardless of which side the bot bet.

        Models with fewer than 10 predictions are logged but their statistics
        carry the ``frozen`` flag so ``optimize_weights`` can skip them.
        """
        performance = {}

        if not self.db_session_factory:
            for model_name in self.model_weights.keys():
                performance[model_name] = {
                    "brier_score": 0.25,
                    "accuracy": 0.5,
                    "num_predictions": 0,
                    "avg_confidence": 0.5,
                }
            return performance

        db = self.db_session_factory()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            # ── Load settled bets with their analysis + market resolution ──
            settled_bets = (
                db.query(Bet, Analysis, WeatherMarket)
                .join(Analysis, Bet.analysis_id == Analysis.id, isouter=True)
                .join(WeatherMarket, Bet.market_id == WeatherMarket.id, isouter=True)
                .filter(
                    Bet.status.in_(["won", "lost", "closed_early"]),
                    func.coalesce(Bet.settled_at, Bet.closed_at) >= cutoff,
                )
                .all()
            )

            # Collect per-model prediction/outcome pairs
            from collections import defaultdict

            model_data: dict[str, list] = defaultdict(list)
            # model_data[model_name] = list of (predicted_prob, actual_yes)

            for _bet, analysis, market in settled_bets:
                if analysis is None or not analysis.model_predictions:
                    continue  # skip bets without per-model predictions

                try:
                    mp = json.loads(analysis.model_predictions)
                except (TypeError, json.JSONDecodeError):
                    continue

                model_probs: dict = mp.get("model_probs", {})
                if not model_probs:
                    continue

                # Resolve YES/NO outcome from market resolution data,
                # NOT from bet.status (which reflects the bot's side,
                # not the market truth).
                outcome_yes = self._resolve_market_outcome(market)

                if outcome_yes is None:
                    continue  # market not yet resolved → skip

                for model_name, prob in model_probs.items():
                    if model_name not in self.model_weights:
                        continue
                    clamped = max(0.01, min(0.99, float(prob)))
                    model_data[model_name].append((clamped, outcome_yes))

            # ── Compute per-model Brier ──────────────────────────────────
            for model_name in self.model_weights.keys():
                records = model_data.get(model_name, [])

                if not records:
                    performance[model_name] = {
                        "brier_score": 0.25,
                        "accuracy": 0.5,
                        "num_predictions": 0,
                        "avg_confidence": 0.5,
                        "frozen": True,
                    }
                    continue

                predictions = [r[0] for r in records]
                outcomes_bool = [r[1] for r in records]

                brier_score = self.calculate_brier_score(predictions, outcomes_bool)
                correct = sum(1 for pred, out in zip(predictions, outcomes_bool) if (pred >= 0.5) == out)
                num_pred = len(predictions)
                accuracy = correct / num_pred if num_pred else 0
                frozen = num_pred < 10

                if frozen:
                    logger.info(
                        "SIA: %s has only %d predictions (< 10) — weight frozen",
                        model_name,
                        num_pred,
                    )

                performance[model_name] = {
                    "brier_score": brier_score,
                    "accuracy": round(accuracy, 4),
                    "num_predictions": num_pred,
                    "avg_confidence": (round(sum(predictions) / num_pred, 4) if num_pred else 0),
                    "frozen": frozen,
                }

            return performance
        except Exception:
            logger.exception("Error analyzing model performance")
            return {}
        finally:
            db.close()

    @staticmethod
    def _resolve_market_outcome(market) -> bool | None:
        """Resolve YES/NO outcome from market resolution data (raw_data JSON).

        Returns ``True`` if the market resolved YES, ``False`` if NO,
        ``None`` if not yet resolved or unknown.
        """
        if market is None:
            return None
        raw = getattr(market, "raw_data", None)
        if not raw:
            return None
        try:
            rd = json.loads(raw) if isinstance(raw, str) else raw
            outcome = rd.get("outcome", "")
            if outcome == "YES":
                return True
            if outcome == "NO":
                return False
        except (TypeError, json.JSONDecodeError):
            pass
        return None

    def optimize_weights(self, performance_data: dict[str, dict]) -> dict[str, float]:
        """Optimize model weights according to Brier Scores.

        Models whose ``frozen`` flag is ``True`` (fewer than 10 predictions)
        keep their current weight unchanged.  Remaining weights are
        redistributed proportionally and normalized to sum to 1.0.
        """
        new_weights = {}

        # Separate frozen vs optimizable models
        frozen_models = {m: self.model_weights.get(m, 0.0) for m, d in performance_data.items() if d.get("frozen", False)}
        optimizable = {m: d for m, d in performance_data.items() if not d.get("frozen", False)}

        if optimizable:
            frozen_total = sum(frozen_models.values())
            remaining_budget = 1.0 - frozen_total

            inverse_scores = {model: max(0.01, 1.0 - data["brier_score"]) for model, data in optimizable.items()}
            total_inv = sum(inverse_scores.values())

            if total_inv > 0:
                for model, score in inverse_scores.items():
                    new_weights[model] = round(score / total_inv * remaining_budget, 4)
            else:
                # All inverse scores collapsed; distribute remaining budget equally
                n_opt = len(optimizable) if optimizable else 1
                for model in optimizable:
                    new_weights[model] = round(remaining_budget / n_opt, 4)
        else:
            # All models frozen — keep existing weights
            new_weights = dict(self.model_weights)

        # Carry frozen weights forward
        new_weights.update(frozen_models)

        logger.info("SIA OPTIMIZASYONU:")
        for model, weight in new_weights.items():
            old_weight = self.model_weights.get(model, 0)
            change = weight - old_weight
            arrow = "^" if change > 0 else "v" if change < 0 else "="
            logger.info(
                "  %s: %.2f%% %s %.2f%% (%+.2f%%)",
                model,
                old_weight * 100,
                arrow,
                weight * 100,
                change * 100,
            )
        # Persist learned weights to disk so the next process
        # restart picks them up. Threshold (0.001) is enforced
        # inside save_weights so we do not spam writes on tiny
        # drift between optimization cycles.
        save_weights(new_weights)

        return new_weights

    def optimize_strategy_params(self, performance_summary: dict[str, float]):
        """SIA Financial Feedback Agent: Autonomous tuning of betting parameters.

        Inspired by hexo-ai/sia architecture: analyzes performance logs and
        updates the Target Agent's (bot) harness/settings.
        """
        if not performance_summary:
            return

        win_rate = performance_summary.get("win_rate", 0.5)
        total_roi = performance_summary.get("total_roi", 0.0)

        # Access the strategy config
        strategy = bot_config.strategy

        logger.info(
            "SIA FINANCIAL FEEDBACK: Win Rate=%.2f%%, ROI=%.2f%%",
            win_rate * 100,
            total_roi,
        )

        # 1. Selectivity (min_edge)
        if win_rate < 0.45:
            # Low win rate: tighten the filter
            old_edge = strategy.min_edge
            strategy.min_edge = min(0.15, strategy.min_edge + 0.01)
            logger.info(
                "  min_edge: %.2f -> %.2f (Selectivity INCREASED due to low Win Rate)",
                old_edge,
                strategy.min_edge,
            )
        elif win_rate > 0.60 and total_roi > 5:
            # High win rate & profit: relax filter to find more trades
            old_edge = strategy.min_edge
            strategy.min_edge = max(0.01, strategy.min_edge - 0.005)
            logger.info(
                "  min_edge: %.2f -> %.2f (Selectivity RELAXED due to high performance)",
                old_edge,
                strategy.min_edge,
            )

        # 2. Risk Appetite (kelly_fraction)
        if total_roi < -10:
            # Significant drawdown: reduce risk
            old_kelly = strategy.kelly_fraction
            strategy.kelly_fraction = max(0.05, strategy.kelly_fraction - 0.05)
            logger.info(
                "  kelly_fraction: %.2f -> %.2f (Risk REDUCED due to drawdown)",
                old_kelly,
                strategy.kelly_fraction,
            )
        elif total_roi > 10 and win_rate > 0.55:
            # High growth: slightly increase risk (capped at 0.25)
            old_kelly = strategy.kelly_fraction
            strategy.kelly_fraction = min(0.25, strategy.kelly_fraction + 0.02)
            logger.info(
                "  kelly_fraction: %.2f -> %.2f (Risk INCREASED due to strong growth)",
                old_kelly,
                strategy.kelly_fraction,
            )

        # Persist changes
        save_strategy_params({"min_edge": strategy.min_edge, "kelly_fraction": strategy.kelly_fraction})

    def run_optimization_cycle(self) -> bool:
        """Execute full SIA optimization cycle (Models + Strategy)."""
        if not self.db_session_factory:
            logger.error("No db_session_factory, cannot run optimization")
            return False

        db = self.db_session_factory()
        try:
            logger.info("SIA Multi-Agent Loop baslatiliyor...")

            # --- 1. Model Weights Optimization (Legacy SIA) ---
            performance = self.analyze_model_performance(days=30)
            new_weights = None
            if performance:
                new_weights = self.optimize_weights(performance)

            # --- 2. Strategy Parameter Optimization (Financial SIA) ---
            # Aggregate overall stats for the feedback agent
            # Include closed_early — these are real exits with real PnL

            _closed_statuses = ("won", "lost", "settled", "closed_early")

            all_closed = db.query(Bet.pnl, Bet.amount).filter(Bet.status.in_(_closed_statuses)).all()
            win_count = sum(1 for b in all_closed if (b.pnl or 0) > 0)
            loss_count = sum(1 for b in all_closed if (b.pnl or 0) <= 0)
            total = win_count + loss_count

            # ROI = realized PnL / total stake (not portfolio.total_value)
            from utils.formulas import roi_pct

            total_realized = sum(b.pnl or 0.0 for b in all_closed)
            total_stake = sum(b.amount or 0.0 for b in all_closed)
            roi = roi_pct(total_realized, total_stake)

            summary = {
                "win_rate": win_count / total if total > 0 else 0.5,
                "total_roi": roi,
                "total_bets": total,
            }
            self.optimize_strategy_params(summary)

            # --- 3. Persist and Record ---
            for model_name, perf in performance.items():
                record = ModelPerformance(
                    model_name=model_name,
                    brier_score=perf["brier_score"],
                    accuracy=perf["accuracy"],
                    num_predictions=perf["num_predictions"],
                    weight=(new_weights or self.model_weights).get(model_name, 0),
                    recorded_at=datetime.now(timezone.utc),
                )
                db.add(record)

            db.commit()
            # Update in-memory state only after successful commit
            if new_weights is not None:
                self.model_weights = new_weights
                if hasattr(self.config, "MODEL_WEIGHTS"):
                    setattr(self.config, "MODEL_WEIGHTS", new_weights)
            logger.info("SIA Loop tamamlandi. Model agirliklari ve strateji parametreleri guncellendi.")
            return True
        except Exception as e:
            db.rollback()
            logger.error("SIA Loop hatasi: %s", e, exc_info=True)
            return False
        finally:
            db.close()
