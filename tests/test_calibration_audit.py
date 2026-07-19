"""Asymmetric calibration audit tests.

A single aggregate Brier score hides one-sided miscalibration. These tests
prove the audit catches a model that is overconfident on YES but fine on NO,
and stays silent when both sides are well calibrated.
"""

from asi_engine.calibration_audit import audit_calibration


def _forecasts(side, preds, outcomes):
    return [{"side": side, "probability": p, "outcome": o} for p, o in zip(preds, outcomes)]


def test_detects_yes_overconfidence_but_not_no():
    # YES: model says ~0.80 but only 0.55 realized -> overconfident
    yes = _forecasts(
        "YES",
        [0.82, 0.80, 0.85, 0.78, 0.83, 0.81, 0.79, 0.84, 0.80, 0.82, 0.80, 0.81],
        [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    )  # mean_pred ~0.81, mean_outcome 0.5
    # NO: well calibrated (says 0.6, realizes 0.6)
    no = _forecasts(
        "NO",
        [0.62, 0.6, 0.59, 0.61, 0.6, 0.58, 0.62, 0.6, 0.59, 0.61, 0.6, 0.58],
        [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    )
    report = audit_calibration(yes + no)
    assert report.yes is not None
    assert report.yes.overconfident is True
    assert report.no is not None
    assert report.no.overconfident is False
    assert report.overconfident is True
    assert any("YES overconfident" in n for n in report.notes)


def test_silent_when_well_calibrated():
    yes = _forecasts(
        "YES",
        [0.82, 0.80, 0.85, 0.78, 0.83, 0.81, 0.79, 0.84, 0.80, 0.82, 0.80, 0.81],
        [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0],
    )  # ~0.81 realized
    no = _forecasts(
        "NO",
        [0.6, 0.62, 0.59, 0.61, 0.6, 0.58, 0.62, 0.6, 0.59, 0.61, 0.6, 0.58],
        [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    )
    report = audit_calibration(yes + no)
    assert report.overconfident is False
    assert report.yes.overconfident is False
    assert report.no.overconfident is False


def test_brier_improves_with_better_predictions():
    bad = _forecasts("YES", [0.9, 0.9, 0.9, 0.9], [0, 0, 0, 0])
    good = _forecasts("YES", [0.55, 0.55, 0.55, 0.55], [1, 0, 1, 0])
    assert audit_calibration(bad).combined_brier > audit_calibration(good).combined_brier


def test_insufficient_high_conf_does_not_false_trigger():
    # Only a few high-confidence forecasts -> not enough to flag overconfidence
    yes = _forecasts("YES", [0.85, 0.8], [0, 0])
    report = audit_calibration(yes)
    assert report.yes.overconfident is False
