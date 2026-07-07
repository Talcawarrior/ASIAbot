"""Layer 3: SIA hourly weight + harness update loop.

This is the "hourly" layer in the 3-layer LLM stack — the fastest,
narrowest layer. Ported from the design of hexo-ai/sia: a 3-agent
Meta/Target/Feedback loop with two update tracks:

  1. **Weight update**: nudges the model_weights dict (same surface as
     Layer 1's mutation ladder, but smaller, faster steps). This is the
     SIA "weight update" branch — it runs even without an LLM.

  2. **Harness update**: asks the LLM to propose a *code patch* to the
     harness (the function that turns per-model forecasts into a YES
     probability). This is the SIA "harness update" branch — it only
     runs when an LLM is available, and the patch must pass a syntax
     check + smoke-eval before being accepted.

Compared to Layer 2 (ASI-Evolve, daily, 50-200 candidates, UCB1):
  - Layer 3 runs hourly (or on-demand).
  - Layer 3 generates 1-3 candidates per run (vs 50-200).
  - Layer 3 may modify the *harness code itself* (Layer 2 only mutates
    weights/params).
  - Layer 3 always starts from the Layer 2 best, never from scratch.

The harness being patched is `asi_engine/sia_harness.py` — a small
file containing one function `predict_yes_probability(forecasts,
weights, days_ahead) -> float`. The LLM is shown the current source,
asked for a diff, the diff is applied, the patched file is imported
in a subprocess (sandbox) and smoke-evaluated against a small OOS
window. Only if the patched harness beats the incumbent does it get
persisted.

If no LLM is available, only the weight-update branch runs (no harness
patches) — this keeps the layer useful in CI.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import random
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from asi_engine.karpathy_weekly import (
    Hypothesis,
    _normalise,
    _uniform_weights,
    evaluate_hypothesis_oos,
)
from asi_engine.llm_client import chat_json
from data_pipeline.unified_datastore import UnifiedDatastore

logger = logging.getLogger("SIA_HOURLY")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data"))
HARNESS_PATH = os.path.join(os.path.dirname(__file__), "sia_harness.py")
HARNESS_BACKUP_PATH = os.path.join(os.path.dirname(__file__), "sia_harness.backup.py")
BEST_PATH = os.path.join(DATA_DIR, "sia_hourly_best.json")
RESULTS_TSV_PATH = os.path.join(DATA_DIR, "sia_hourly_results.tsv")


# ---------------------------------------------------------------------------
# Default harness (created on first run if missing)
# ---------------------------------------------------------------------------

DEFAULT_HARNESS_SRC = '''"""SIA harness — the function that turns per-model forecasts into a YES prob.

This file is the target of Layer 3 harness updates. The LLM may propose
patches to `predict_yes_probability`. Each patch must pass a syntax
check + smoke-eval before being accepted.
"""

from __future__ import annotations

import math


def predict_yes_probability(
    forecasts: dict[str, float],
    weights: dict[str, float],
    threshold: float,
    days_ahead: int = 1,
) -> float:
    """Compute P(YES) from per-model temperature forecasts.

    Default implementation: weighted mean of forecasts -> z-score vs
    threshold -> Normal CDF.

    Args:
        forecasts: dict of {model_name: forecasted_temperature}
        weights: dict of {model_name: weight} (must sum to 1.0)
        threshold: market threshold temperature
        days_ahead: forecast horizon (1-7)

    Returns:
        P(YES) in [0.01, 0.99]
    """
    if not forecasts:
        return 0.5

    wsum = sum(weights.get(m, 0.0) for m in forecasts)
    if wsum <= 0:
        return 0.5

    weighted_mean = sum(weights.get(m, 0.0) * f for m, f in forecasts.items()) / wsum
    variance = sum(
        weights.get(m, 0.0) * (f - weighted_mean) ** 2
        for m, f in forecasts.items()
    ) / wsum
    std = math.sqrt(variance) if variance > 0 else 1.0
    effective_std = std * math.sqrt(max(days_ahead, 1))

    z = (weighted_mean - threshold) / (effective_std + 1e-5)
    p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return min(max(p, 0.01), 0.99)
'''


def _ensure_harness() -> None:
    """Create the default harness file if it doesn't exist."""
    if not os.path.exists(HARNESS_PATH):
        with open(HARNESS_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_HARNESS_SRC)
        logger.info("Wrote default SIA harness to %s", HARNESS_PATH)


def _load_harness_source() -> str:
    _ensure_harness()
    with open(HARNESS_PATH, encoding="utf-8") as f:
        return f.read()


def _import_harness():
    """Import the harness module fresh (forces reload after patch)."""
    _ensure_harness()
    # Add asi_engine to sys.path if not present
    ae_dir = os.path.dirname(__file__)
    if ae_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(ae_dir))
    import asi_engine.sia_harness as mod  # type: ignore

    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# 3 Agents: Meta, Target, Feedback
# ---------------------------------------------------------------------------


@dataclass
class SIAState:
    """State carried between agents in one SIA cycle."""

    parent_hypothesis: Hypothesis
    parent_stats: dict[str, float]
    candidate_hypothesis: Hypothesis | None = None
    candidate_stats: dict[str, float] | None = None
    harness_patched: bool = False
    harness_diff: str = ""
    accepted: bool = False
    rejection_reason: str = ""


class MetaAgent:
    """Orchestrates the cycle: picks what to mutate (weights vs harness).

    The Meta agent looks at the parent's recent stats:
      - If Brier is high (>0.25), the harness is the bottleneck → suggest
        harness patch (if LLM available).
      - If Brier is OK but Sharpe is low, weights are the bottleneck →
        suggest weight mutation.
      - If both are bad, try both.
    """

    def __init__(self, use_llm: bool):
        self.use_llm = use_llm

    def decide(self, state: SIAState) -> list[str]:
        actions: list[str] = []
        stats = state.parent_stats

        brier = stats.get("brier_score", 0.25)
        sharpe = stats.get("sharpe", 0.0)
        trades = stats.get("total_trades", 0)

        # If too few trades, weights are too restrictive
        if trades < 10:
            actions.append("weight_mutation")

        # If Brier is bad, harness is the bottleneck
        if brier > 0.25 and self.use_llm:
            actions.append("harness_patch")

        # If Sharpe is bad, weights need tuning
        if sharpe < 0.5:
            actions.append("weight_mutation")

        # Always try at least one action
        if not actions:
            actions.append("weight_mutation")

        return actions


class TargetAgent:
    """Generates the candidate (weight mutation or harness patch).

    For weight mutations: small +/- 1-3% shifts on random models.
    For harness patches: asks the LLM for a diff to predict_yes_probability.
    """

    def __init__(self, use_llm: bool, seed: int = 42):
        self.use_llm = use_llm
        self.rng = random.Random(seed)

    def mutate_weights(self, parent: Hypothesis) -> Hypothesis:
        """Small weight mutation: pick 2 models at random, shift 1-3%."""
        models = list(parent.model_weights.keys())
        if len(models) < 2:
            return parent

        boost, trim = self.rng.sample(models, 2)
        delta = self.rng.uniform(0.01, 0.03)

        new_weights = dict(parent.model_weights)
        new_weights[boost] = max(0.01, new_weights[boost] + delta)
        new_weights[trim] = max(0.01, new_weights[trim] - delta)
        new_weights = _normalise(new_weights)

        # Also randomly nudge min_edge / kelly / blend_weight by a tiny amount
        new_min_edge = max(
            0.01,
            min(0.15, parent.min_edge + self.rng.choice([-0.01, -0.005, 0, 0.005, 0.01])),
        )
        new_kelly = max(
            0.05,
            min(
                0.30,
                parent.kelly_fraction + self.rng.choice([-0.02, -0.01, 0, 0.01, 0.02]),
            ),
        )
        new_blend = max(
            0.35,
            min(
                1.0,
                parent.blend_weight + self.rng.choice([-0.05, -0.02, 0, 0.02, 0.05]),
            ),
        )

        return Hypothesis(
            description=f"SIA hourly: +{delta:.3f} {boost} / -{delta:.3f} {trim}",
            model_weights=new_weights,
            min_edge=round(new_min_edge, 4),
            kelly_fraction=round(new_kelly, 4),
            max_bet_pct=parent.max_bet_pct,
            blend_weight=round(new_blend, 4),
            tail_filter_enabled=parent.tail_filter_enabled,
            tail_filter_threshold_high=parent.tail_filter_threshold_high,
            tail_filter_threshold_low=parent.tail_filter_threshold_low,
            tail_filter_correction_high=parent.tail_filter_correction_high,
            tail_filter_correction_low=parent.tail_filter_correction_low,
            source="sia_weight_mutation",
        )

    def propose_harness_patch(self, parent: Hypothesis, stats: dict[str, float]) -> str | None:
        """Ask the LLM for a patched harness source.

        Returns the new full source code, or None on failure / no LLM.
        Uses the shared ``asi_engine.llm_client`` helper (ZAI / GLM only).
        """
        if not self.use_llm:
            return None

        current_src = _load_harness_source()

        prompt = (
            "You are the Target agent in a SIA (Self-Improving Algorithm) loop.\n"
            "Your job: propose a patched version of `predict_yes_probability`.\n\n"
            f"Current source:\n```python\n{current_src}\n```\n\n"
            f"Current parent stats: {json.dumps(stats, indent=2)}\n\n"
            f"Parent weights: {json.dumps(parent.model_weights, indent=2)}\n\n"
            "Requirements:\n"
            "1. Keep the same function signature.\n"
            "2. Return only the FULL patched Python source code, no prose.\n"
            "3. The patched function must still return a float in [0.01, 0.99].\n"
            "4. Try ONE focused improvement (e.g. temperature bias correction, "
            "non-linear ensemble combination, volatility-scaled z-score).\n"
        )

        raw = chat_json(
            prompt,
            layer="SIA",
            temperature=0.5,
            max_tokens=4000,
        )
        if not raw:
            return None

        # Strip markdown fences if present
        if "```python" in raw:
            raw = raw.split("```python", 1)[1].split("```", 1)[0]
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0]

        # Sanity check: must contain the function definition
        if "def predict_yes_probability" not in raw:
            logger.warning("LLM patch missing function definition — rejecting")
            return None

        return raw.strip()


class FeedbackAgent:
    """Evaluates the candidate and decides accept/reject.

    For weight mutations: uses the standard Layer 1 OOS evaluator.
    For harness patches: writes the patched source to a temp file,
    imports it in a subprocess (sandbox), runs smoke eval, accepts only
    if it beats the incumbent on Sharpe.
    """

    def __init__(self, brier_df: pd.DataFrame, splits: list[dict[str, Any]]):
        self.brier_df = brier_df
        self.splits = splits

    def evaluate_weight_mutation(self, hyp: Hypothesis) -> dict[str, float]:
        per_split = [evaluate_hypothesis_oos(self.brier_df, s["test_indices"], hyp) for s in self.splits]
        return _mean_stats(per_split)

    def evaluate_harness_patch(self, patched_src: str) -> tuple[dict[str, float] | None, str]:
        """Evaluate a harness patch in a subprocess sandbox.

        LLM-generated code is NEVER executed in the main process.
        Returns (stats, error_message). If stats is None, the patch was
        rejected (syntax error, runtime error, or import failure).
        """
        import subprocess

        # Write LLM source to a temp file
        src_fd, src_path = tempfile.mkstemp(suffix=".py", prefix="sia_patch_")
        try:
            with os.fdopen(src_fd, "w", encoding="utf-8") as f:
                f.write(patched_src)

            # Syntax check in main process (cheap, safe — compile() doesn't exec)
            try:
                with open(src_path, encoding="utf-8") as f:
                    compile(f.read(), src_path, "exec")
            except SyntaxError as e:
                return None, f"SyntaxError: {e}"

            # Prepare input data for subprocess (brier rows for OOS eval)
            brier_rows: list[dict] = []
            if not self.brier_df.empty:
                prob_cols = [c for c in self.brier_df.columns if c.startswith("prob_")]
                if prob_cols:
                    for _, row in self.brier_df.iterrows():
                        realized = row.get("realized_yes")
                        if realized is None or pd.isna(realized):
                            continue
                        r: dict[str, Any] = {"realized_yes": float(realized)}
                        for c in prob_cols:
                            v = row.get(c)
                            if v is not None and not pd.isna(v):
                                r[c] = float(v)
                        brier_rows.append(r)

            inp_fd, inp_path = tempfile.mkstemp(suffix=".json", prefix="sia_input_")
            try:
                with os.fdopen(inp_fd, "w", encoding="utf-8") as f:
                    json.dump({"brier_rows": brier_rows}, f)

                # Run smoke test + OOS eval in isolated subprocess
                runner = os.path.join(os.path.dirname(__file__), "_sandbox_runner.py")
                result = subprocess.run(
                    [sys.executable, runner, src_path, inp_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode != 0:
                    err = result.stdout.strip() or result.stderr.strip()
                    # Try to parse structured error from JSON output
                    try:
                        err_obj = json.loads(err)
                        return None, err_obj.get("error", err)
                    except (json.JSONDecodeError, AttributeError):
                        return None, f"Subprocess error: {err}"

                stats = json.loads(result.stdout.strip())
                if not stats:
                    return None, "Empty subprocess output"
                return stats, ""

            finally:
                try:
                    os.unlink(inp_path)
                except OSError:
                    pass

        except subprocess.TimeoutExpired:
            return None, "Sandbox timeout (>30s)"
        except Exception as e:
            return None, f"Unexpected error: {e}"
        finally:
            try:
                os.unlink(src_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _mean_stats(per_split: list[dict[str, float]]) -> dict[str, float]:
    if not per_split:
        return {
            "sharpe": 0.0,
            "roi_pct": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "brier_score": 0.25,
            "total_pnl": 0.0,
            "total_staked": 0.0,
        }
    keys = ["sharpe", "roi_pct", "win_rate", "brier_score", "total_pnl", "total_staked"]
    out = {k: sum(s.get(k, 0.0) for s in per_split) / len(per_split) for k in keys}
    out["total_trades"] = int(sum(s.get("total_trades", 0) for s in per_split))
    out["sharpe"] = round(out["sharpe"], 4)
    out["roi_pct"] = round(out["roi_pct"], 4)
    out["brier_score"] = round(out["brier_score"], 4)
    out["win_rate"] = round(out["win_rate"], 4)
    return out


def _load_best() -> tuple[Hypothesis | None, dict[str, float] | None]:
    if not os.path.exists(BEST_PATH):
        return None, None
    try:
        with open(BEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        stats = data.pop("stats", {})
        data.pop("saved_at", "")
        hyp = Hypothesis(**{k: v for k, v in data.items() if k in Hypothesis.__dataclass_fields__})
        return hyp, stats
    except Exception as e:
        logger.warning("Could not load SIA best: %s", e)
        return None, None


def _save_best(hyp: Hypothesis, stats: dict[str, float]) -> None:
    os.makedirs(os.path.dirname(BEST_PATH), exist_ok=True)
    payload = {
        **hyp.to_dict(),
        "stats": stats,
        "saved_at": datetime.now(UTC).isoformat(),
    }
    with open(BEST_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _append_results_tsv(
    cycle: int,
    action: str,
    hyp: Hypothesis,
    stats: dict[str, float],
    status: str,
    note: str = "",
) -> None:
    os.makedirs(os.path.dirname(RESULTS_TSV_PATH), exist_ok=True)
    header = "cycle\ttimestamp\taction\tdescription\tsource\tsharpe\troi_pct\tbrier\ttrades\tstatus\tnote\n"
    if not os.path.exists(RESULTS_TSV_PATH):
        with open(RESULTS_TSV_PATH, "w", encoding="utf-8") as f:
            f.write(header)
    with open(RESULTS_TSV_PATH, "a", encoding="utf-8") as f:
        f.write(
            f"{cycle}\t{datetime.now(UTC).isoformat()}\t{action}\t"
            f"{hyp.description!r}\t{hyp.source}\t"
            f"{stats.get('sharpe', 0.0)}\t{stats.get('roi_pct', 0.0)}\t"
            f"{stats.get('brier_score', 0.25)}\t{stats.get('total_trades', 0)}\t"
            f"{status}\t{note}\n"
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_sia_hourly(
    use_llm: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Run one SIA hourly cycle.

    Returns a summary dict with the cycle's actions and outcomes.
    """
    random.seed(seed)
    _ensure_harness()

    # 1. Pull unified Brier dataset + splits
    ds = UnifiedDatastore()
    try:
        brier_df = ds.build_brier_dataset()
    except Exception as e:
        logger.warning(
            "build_brier_dataset() raised %s — run polymarket_ingest with the "
            "weather market parser first. Returning early.",
            e,
        )
        return {"error": "brier_dataset_unavailable", "detail": str(e), "cycles_run": 0}

    if brier_df is None or brier_df.empty:
        logger.error("Brier dataset is empty")
        return {"error": "empty_brier_dataset", "cycles_run": 0}

    # Add per-model prob columns (tries real forecast join, falls back to synthetic)
    from asi_engine.karpathy_weekly import add_per_model_probabilities

    brier_df = add_per_model_probabilities(brier_df, ds=ds)

    splits = ds.build_walk_forward_splits()
    if not splits:
        splits = [
            {
                "split_n": 1,
                "test_indices": brier_df.index.tolist(),
                "train_indices": [],
            }
        ]

    # 2. Load parent (SIA's own best, or Layer 2 best, or Layer 1 best, or prior)
    parent_hyp, parent_stats = _load_best()
    if parent_hyp is None:
        # Try Layer 2 (ASI-Evolve) best
        from asi_engine.asi_evolve import _load_best as load_asi_evolve_best
        from asi_engine.karpathy_weekly import _load_best as load_karpathy_best

        conn = None
        try:
            from asi_engine.asi_evolve import _get_db

            conn = _get_db()
            parent_hyp, parent_stats = load_asi_evolve_best(conn)
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
        if parent_hyp is None:
            parent_hyp = load_karpathy_best()
        if parent_hyp is None:
            parent_hyp = Hypothesis(
                description="Uniform prior (SIA seed)",
                model_weights=_uniform_weights(),
                min_edge=0.30,  # SAFETY CLAMP
                kelly_fraction=0.15,
                max_bet_pct=0.05,
                blend_weight=0.65,
            )
            # Re-eval on current splits
            feedback = FeedbackAgent(brier_df, splits)
            parent_stats = feedback.evaluate_weight_mutation(parent_hyp)
        else:
            # Re-eval Layer 1/2 best on current splits
            feedback = FeedbackAgent(brier_df, splits)
            parent_stats = feedback.evaluate_weight_mutation(parent_hyp)
        _save_best(parent_hyp, parent_stats)

    state = SIAState(parent_hypothesis=parent_hyp, parent_stats=parent_stats)

    # 3. Run Meta → Target → Feedback
    meta = MetaAgent(use_llm=use_llm)
    target = TargetAgent(use_llm=use_llm, seed=seed)
    feedback = FeedbackAgent(brier_df, splits)

    actions = meta.decide(state)
    logger.info("SIA cycle actions: %s", actions)

    best_hyp = parent_hyp
    best_stats = parent_stats
    actions_taken: list[dict[str, Any]] = []

    for action in actions:
        if action == "weight_mutation":
            cand_hyp = target.mutate_weights(parent_hyp)
            cand_stats = feedback.evaluate_weight_mutation(cand_hyp)

            improved = (
                cand_stats["sharpe"] > best_stats.get("sharpe", -1e9)
                and cand_stats["brier_score"] <= best_stats.get("brier_score", 1.0) * 1.05
                and cand_stats["total_trades"] >= 3
            )

            if improved:
                logger.info(
                    "  [weight_mutation] ✓ sharpe %.3f > %.3f",
                    cand_stats["sharpe"],
                    best_stats.get("sharpe", 0.0),
                )
                best_hyp = cand_hyp
                best_stats = cand_stats
                _save_best(cand_hyp, cand_stats)
                _append_results_tsv(1, "weight_mutation", cand_hyp, cand_stats, "keep")
                actions_taken.append(
                    {
                        "action": "weight_mutation",
                        "status": "keep",
                        "hypothesis": cand_hyp.to_dict(),
                        "stats": cand_stats,
                    }
                )
            else:
                logger.info(
                    "  [weight_mutation] ✗ sharpe %.3f ≤ %.3f",
                    cand_stats["sharpe"],
                    best_stats.get("sharpe", 0.0),
                )
                _append_results_tsv(1, "weight_mutation", cand_hyp, cand_stats, "reject")
                actions_taken.append(
                    {
                        "action": "weight_mutation",
                        "status": "reject",
                        "hypothesis": cand_hyp.to_dict(),
                        "stats": cand_stats,
                    }
                )

        elif action == "harness_patch":
            patched_src = target.propose_harness_patch(parent_hyp, parent_stats)
            if patched_src is None:
                logger.info("  [harness_patch] skipped (no LLM or proposal failed)")
                actions_taken.append(
                    {
                        "action": "harness_patch",
                        "status": "skipped",
                        "reason": "no_llm_or_proposal_failed",
                    }
                )
                continue

            cand_stats, err = feedback.evaluate_harness_patch(patched_src)
            if cand_stats is None:
                logger.info("  [harness_patch] ✗ rejected: %s", err)
                _append_results_tsv(
                    1,
                    "harness_patch",
                    parent_hyp,
                    {"sharpe": 0, "roi_pct": 0, "brier_score": 1, "total_trades": 0},
                    "reject",
                    note=err,
                )
                actions_taken.append(
                    {
                        "action": "harness_patch",
                        "status": "reject",
                        "reason": err,
                    }
                )
                continue

            # Accept harness patch only if Brier improves meaningfully
            improved = cand_stats["brier_score"] < best_stats.get("brier_score", 1.0) * 0.95
            if improved:
                logger.info(
                    "  [harness_patch] ✓ brier %.4f < %.4f — persisting patched harness",
                    cand_stats["brier_score"],
                    best_stats.get("brier_score", 1.0),
                )
                # Persist the patched harness
                with open(HARNESS_PATH, "w", encoding="utf-8") as f:
                    f.write(patched_src)
                # Reload
                import asi_engine.sia_harness as harness_mod

                importlib.reload(harness_mod)
                _append_results_tsv(1, "harness_patch", parent_hyp, cand_stats, "keep")
                actions_taken.append(
                    {
                        "action": "harness_patch",
                        "status": "keep",
                        "stats": cand_stats,
                        "diff_preview": patched_src[:500],
                    }
                )
            else:
                logger.info(
                    "  [harness_patch] ✗ brier %.4f ≥ %.4f",
                    cand_stats["brier_score"],
                    best_stats.get("brier_score", 1.0) * 0.95,
                )
                _append_results_tsv(1, "harness_patch", parent_hyp, cand_stats, "reject")
                actions_taken.append(
                    {
                        "action": "harness_patch",
                        "status": "reject",
                        "stats": cand_stats,
                    }
                )

    logger.info(
        "SIA hourly done. Best: sharpe=%.3f brier=%.4f desc=%r",
        best_stats.get("sharpe", 0.0),
        best_stats.get("brier_score", 0.25),
        best_hyp.description,
    )

    return {
        "cycles_run": 1,
        "actions_taken": actions_taken,
        "best_hypothesis": best_hyp.to_dict(),
        "best_stats": best_stats,
        "n_splits": len(splits),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="SIA hourly weight + harness update loop")
    parser.add_argument("--llm", action="store_true", help="Use LLM for harness patches")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    summary = run_sia_hourly(use_llm=args.llm, seed=args.seed)
    print(json.dumps(summary, indent=2, default=str))
