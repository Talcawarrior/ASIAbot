"""Probability calibration via Platt scaling (logistic calibration).

Fits a logistic function to map raw probability estimates → calibrated
probabilities using historical (prediction, outcome) pairs:

    p_calibrated = 1 / (1 + exp(-(a * logit(p_raw) + b)))

The a, b parameters are learned by minimizing negative log-likelihood
on historical data, then persisted to ``data/prob_calibration.json``
so the calibration survives bot restarts.
"""

import json
import logging
import math
from pathlib import Path

logger = logging.getLogger("CALIBRATOR")

# Persistence path — one level up from utils/ into data/
CALIB_PATH = Path(__file__).resolve().parent.parent / "data" / "prob_calibration.json"


def _logit(p: float) -> float:
    """Logit function (log-odds) with numerical stability clamps."""
    p = max(1e-10, min(1 - 1e-10, p))
    return math.log(p / (1 - p))


class ProbabilityCalibrator:
    """Platt (logistic) scaling calibrator for binary probability estimates.

    Parameters
    ----------
    auto_train : bool
        If True, attempts to fit on historical data from the bot DB when
        *calibrate()* is first called (or explicitly via :meth:`fit_from_db`).
        Default ``True``.

    Examples
    --------
    >>> cal = ProbabilityCalibrator()
    >>> cal.fit([0.1, 0.5, 0.9], [0.0, 1.0, 1.0])
    >>> cal.calibrate(0.95)  # doctest: +SKIP
    0.8723
    """

    def __init__(self, auto_train: bool = True):
        self.a: float = 1.0  # slope (1 = identity)
        self.b: float = 0.0  # intercept (0 = identity)
        self.is_trained: bool = False
        self._n_fit: int = 0  # number of training samples

        self._load()
        if auto_train and not self.is_trained:
            try:
                self.fit_from_db()
            except Exception as exc:
                logger.warning("Auto-train skipped: %s", exc)

    # ── public API ────────────────────────────────────────────────────────

    def calibrate(self, p: float) -> float:
        """Apply Platt scaling to a raw probability.

        Returns the calibrated probability clamped to ``[0.01, 0.99]``.
        If the calibrator has not been trained yet this is a no-op.
        """
        if not self.is_trained:
            return p
        logit_p = _logit(p)
        calibrated = 1.0 / (1.0 + math.exp(-(self.a * logit_p + self.b)))
        return max(0.01, min(0.99, calibrated))

    def fit(self, predictions: list[float], outcomes: list[float]) -> None:
        """Fit Platt scaling parameters via Nelder-Mead optimisation.

        Parameters
        ----------
        predictions : list[float]
            Raw predicted probabilities (in ``[0, 1]``).
        outcomes : list[float]
            Actual binary outcomes (0.0 or 1.0).

        Raises
        ------
        ValueError
            If fewer than 10 training pairs are provided.
        """
        if len(predictions) < 10:
            raise ValueError(f"Need at least 10 training pairs, got {len(predictions)}")
        if len(predictions) != len(outcomes):
            raise ValueError(f"predictions ({len(predictions)}) / outcomes ({len(outcomes)}) length mismatch")

        # scipy is already a soft dependency (used by normal_cdf)
        from scipy.optimize import minimize  # type: ignore[import-untyped]

        def _nll(params: list[float]) -> float:
            a, b = params
            nll = 0.0
            for p, y in zip(predictions, outcomes, strict=False):
                lp = _logit(p)
                pc = 1.0 / (1.0 + math.exp(-(a * lp + b)))
                pc = max(1e-15, min(1 - 1e-15, pc))
                nll -= y * math.log(pc) + (1.0 - y) * math.log(1.0 - pc)
            return nll

        result = minimize(
            _nll,
            [self.a, self.b],
            method="L-BFGS-B",
            bounds=[(0.01, 10.0), (-10.0, 10.0)],  # force a > 0 (positive slope)
        )
        self.a, self.b = result.x
        self.is_trained = True
        self._n_fit = len(predictions)
        self._save()
        logger.info(
            "Calibrator trained: a=%.4f, b=%.4f  (n=%d, nll=%.2f)",
            self.a,
            self.b,
            self._n_fit,
            result.fun,
        )

    def fit_from_db(self, db_path: str | None = None) -> int:
        """Train the calibrator on historical settled bets from the bot DB.

        Queries the ``analyses`` + ``bets`` tables to collect
        (``estimated_probability``, actual outcome) pairs for every
        uniquely settled bet.

        Parameters
        ----------
        db_path : str, optional
            Path to the SQLite database.  Falls back to the production path
            used by the bot (``data/bot.db``).

        Returns
        -------
        int
            Number of training pairs used.
        """
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent / "data" / "bot.db")

        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT b.id, a.estimated_probability, b.status, b.side
                FROM bets b
                JOIN analyses a ON a.id = b.analysis_id
                WHERE b.status IN ('won', 'lost')
                  AND a.estimated_probability IS NOT NULL
            """)
            rows = cur.fetchall()
        finally:
            conn.close()

        if len(rows) < 10:
            logger.warning(
                "fit_from_db: only %d settled bets — need ≥ 10, skipping",
                len(rows),
            )
            return 0

        predictions: list[float] = []
        outcomes: list[float] = []
        seen = set()
        for bid, p, status, side in rows:
            if bid in seen:
                continue
            seen.add(bid)
            predictions.append(float(p))
            # outcome = 1.0 when YES actually happened (regardless of bet side)
            # YES side + won  → YES happened → 1.0
            # YES side + lost → YES didn't happen → 0.0
            # NO  side + won  → NO happened (YES didn't) → 0.0
            # NO  side + lost → NO didn't happen (YES did) → 1.0
            yes_happened = (side and side.upper() == "YES") == (status == "won")
            outcomes.append(1.0 if yes_happened else 0.0)

        self.fit(predictions, outcomes)
        return len(predictions)

    # ── persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CALIB_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "a": self.a,
                    "b": self.b,
                    "trained": self.is_trained,
                    "n_fit": self._n_fit,
                },
                f,
            )

    def _load(self) -> None:
        if not CALIB_PATH.exists():
            return
        try:
            with open(CALIB_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self.a = data.get("a", 1.0)
            self.b = data.get("b", 0.0)
            self.is_trained = data.get("trained", False)
            self._n_fit = data.get("n_fit", 0)
            if self.is_trained:
                logger.info(
                    "Loaded calibrator: a=%.4f, b=%.4f (n=%d)",
                    self.a,
                    self.b,
                    self._n_fit,
                )
        except Exception as exc:
            logger.warning("Could not load calibrator: %s", exc)


# Module-level singleton — imported by calculator / estimate_probability
_calibrator: ProbabilityCalibrator | None = None


def get_calibrator() -> ProbabilityCalibrator:
    """Return the module-level singleton calibrator."""
    global _calibrator
    if _calibrator is None:
        _calibrator = ProbabilityCalibrator(auto_train=True)
    return _calibrator


def calibrate_probability(p: float) -> float:
    """Convenience: calibrate a single probability using the singleton."""
    return get_calibrator().calibrate(p)
