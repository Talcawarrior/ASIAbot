"""Asymmetric calibration audit for probabilistic forecasts.

Prediction-market models are most often killed by *one-sided* miscalibration:
the bot is overconfident on YES but fine on NO (or vice-versa). A single
aggregate Brier score hides this. This module scores YES and NO sides
separately and flags overconfidence — when the model says "80%" but the event
happens only ~60% of the time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SideCalibration:
    side: str
    n: int
    brier: float
    mean_pred: float
    mean_outcome: float
    overconfident: bool = False


@dataclass
class CalibrationReport:
    yes: SideCalibration | None = None
    no: SideCalibration | None = None
    combined_brier: float = 0.0
    overconfident: bool = False
    notes: list[str] = field(default_factory=list)


def _brier(preds: list[float], outcomes: list[float]) -> float:
    if not preds:
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def audit_calibration(
    forecasts: list[dict],
    high_conf_threshold: float = 0.65,
    tolerance: float = 0.10,
) -> CalibrationReport:
    """Score calibration per side and detect overconfidence.

    ``forecasts`` is a list of dicts with:
        ``side``       : "YES" or "NO" (the side the model bet on)
        ``probability``: model probability for that side (0..1)
        ``outcome``    : 1.0 if that side won, 0.0 otherwise

    Overconfidence (per side) fires when at least 10 high-confidence forecasts
    exist and the realized frequency is more than ``tolerance`` below the mean
    stated probability.
    """
    yes_items = [f for f in forecasts if f.get("side") == "YES"]
    no_items = [f for f in forecasts if f.get("side") == "NO"]

    def _side(side: str, items: list[dict]) -> SideCalibration | None:
        if not items:
            return None
        preds = [float(i["probability"]) for i in items]
        outs = [float(i["outcome"]) for i in items]
        mean_pred = _mean(preds)
        mean_out = _mean(outs)
        hc = [o for p, o in zip(preds, outs) if p >= high_conf_threshold]
        over = False
        if len(hc) >= 10 and mean_pred - mean_out > tolerance:
            over = True
        return SideCalibration(
            side=side,
            n=len(items),
            brier=_brier(preds, outs),
            mean_pred=mean_pred,
            mean_outcome=mean_out,
            overconfident=over,
        )

    yes = _side("YES", yes_items)
    no = _side("NO", no_items)

    all_preds = [float(f["probability"]) for f in forecasts]
    all_outs = [float(f["outcome"]) for f in forecasts]
    combined = _brier(all_preds, all_outs)

    notes: list[str] = []
    overconfident = False
    if yes and yes.overconfident:
        overconfident = True
        notes.append(f"YES overconfident: says {yes.mean_pred:.2f} but only {yes.mean_outcome:.2f} realized (n={yes.n})")
    if no and no.overconfident:
        overconfident = True
        notes.append(f"NO overconfident: says {no.mean_pred:.2f} but only {no.mean_outcome:.2f} realized (n={no.n})")

    return CalibrationReport(
        yes=yes,
        no=no,
        combined_brier=combined,
        overconfident=overconfident,
        notes=notes,
    )
