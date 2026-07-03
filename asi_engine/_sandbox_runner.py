"""Subprocess sandbox for evaluating LLM-generated harness code.

Called by FeedbackAgent.evaluate_harness_patch() via subprocess.run().
Receives source code path + input data path, returns JSON results.

This script runs in an isolated process — untrusted LLM code cannot
escape to the main bot process.
"""

from __future__ import annotations

import importlib.util
import json
import sys

# Must match karpathy_weekly.DEFAULT_MODELS
DEFAULT_MODELS = [
    "GFS",
    "ECMWF",
    "GEM",
    "ICON",
    "JMA",
    "CMA",
    "UKMO",
    "MeteoFrance",
]


def _uniform_weights() -> dict[str, float]:
    w = 1.0 / len(DEFAULT_MODELS)
    return {m: w for m in DEFAULT_MODELS}


def _load_module(src_path: str):
    """Import a .py file as a module (untrusted code)."""
    spec = importlib.util.spec_from_file_location("_llm_patch", src_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _smoke_test(mod) -> str | None:
    """Run basic sanity checks. Returns error string or None (OK)."""
    if not hasattr(mod, "predict_yes_probability"):
        return "Missing predict_yes_probability function"
    test_fc = {m: 25.0 + i for i, m in enumerate(DEFAULT_MODELS)}
    try:
        p = mod.predict_yes_probability(
            forecasts=test_fc,
            weights=_uniform_weights(),
            threshold=30.0,
            days_ahead=2,
        )
        if not isinstance(p, (int, float)) or not 0.0 <= p <= 1.0:
            return f"Smoke test returned invalid value: {p!r}"
    except Exception as e:
        return f"Smoke test exception: {e}"
    return None


def _oos_eval(mod, brier_rows: list[dict]) -> dict[str, float]:
    """Run Brier-score OOS evaluation using the patched harness."""
    if not brier_rows:
        return {"brier_score": 0.25, "n_rows": 0}

    prob_cols = [c for c in brier_rows[0] if c.startswith("prob_")] if brier_rows else []
    brier_errors: list[float] = []
    for row in brier_rows:
        realized = row.get("realized_yes")
        if realized is None:
            continue
        probs = [float(row[c]) for c in prob_cols if row.get(c) is not None]
        if not probs:
            continue
        forecasts = {DEFAULT_MODELS[i]: probs[i] if i < len(probs) else 0.5 for i in range(len(DEFAULT_MODELS))}
        try:
            p_yes = mod.predict_yes_probability(
                forecasts=forecasts,
                weights=_uniform_weights(),
                threshold=0.5,
                days_ahead=1,
            )
            p_yes = max(0.01, min(0.99, float(p_yes)))
        except Exception:
            continue
        brier_errors.append((p_yes - float(realized)) ** 2)

    if not brier_errors:
        return {"brier_score": 0.25, "n_rows": 0}
    brier = sum(brier_errors) / len(brier_errors)
    return {
        "sharpe": 0.0,
        "roi_pct": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
        "brier_score": round(brier, 4),
        "total_pnl": 0.0,
        "total_staked": 0.0,
        "n_rows": len(brier_errors),
    }


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"error": "Usage: _sandbox_runner.py <src_path> <input_json>"}))
        sys.exit(1)

    src_path = sys.argv[1]
    input_path = sys.argv[2]

    with open(input_path, encoding="utf-8") as f:
        inp = json.load(f)

    mod = _load_module(src_path)
    if mod is None:
        print(json.dumps({"error": "Could not load module"}))
        sys.exit(1)

    # Smoke test
    err = _smoke_test(mod)
    if err:
        print(json.dumps({"error": err}))
        sys.exit(1)

    # OOS eval
    stats = _oos_eval(mod, inp.get("brier_rows", []))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
