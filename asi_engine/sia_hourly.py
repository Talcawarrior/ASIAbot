"""Layer 3: SIA hourly weight update loop.

This is the "hourly" layer in the 3-layer LLM stack — the fastest,
narrowest layer. Ported from the design of hexo-ai/sia:

  1. **Weight update**: nudges the model_weights dict (same surface as
     Layer 1's mutation ladder, but smaller, faster steps). This is the
     SIA "weight update" branch — it runs even without an LLM.

Compared to Layer 2 (ASI-Evolve, daily, 50-200 candidates, UCB1):
  - Layer 3 runs hourly (or on-demand).
  - Layer 3 generates 1-3 candidates per run (vs 50-200).
  - Layer 3 only mutates weights/params (Layer 2 also mutates weights/params).
  - Layer 3 always starts from the Layer 2 best, never from scratch.

If no LLM is available, the weight-update branch runs — this keeps the
layer useful in CI.
"""

from __future__ import annotations

import json
import logging
import os
import random
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
from data_pipeline.unified_datastore import UnifiedDatastore

logger = logging.getLogger("SIA_HOURLY")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "data"))
BEST_PATH = os.path.join(DATA_DIR, "sia_hourly_best.json")
RESULTS_TSV_PATH = os.path.join(DATA_DIR, "sia_hourly_results.tsv")


# ---------------------------------------------------------------------------
# 3 Agents: Meta, Target, Feedback (weight mutation only)
# ---------------------------------------------------------------------------


@dataclass
class SIAState:
    """State carried between agents in one SIA cycle."""

    parent_hypothesis: Hypothesis
    parent_stats: dict[str, float]
    candidate_hypothesis: Hypothesis | None = None
    candidate_stats: dict[str, float] | None = None
    accepted: bool = False
    rejection_reason: str = ""


class MetaAgent:
    """Orchestrates the cycle: decides what to mutate (weights only)."""

    def __init__(self, use_llm: bool = False):
        self.use_llm = use_llm  # kept for API compatibility

    def decide(self, state: SIAState) -> list[str]:
        actions: list[str] = []
        stats = state.parent_stats

        brier = stats.get("brier_score", 0.25)
        sharpe = stats.get("sharpe", 0.0)
        trades = stats.get("total_trades", 0)

        # If too few trades, weights are too restrictive
        if trades < 10:
            actions.append("weight_mutation")

        # If Sharpe is bad, weights need tuning
        if sharpe < 0.5:
            actions.append("weight_mutation")

        # If Brier is bad, also try weight mutation (harness patching removed)
        if brier > 0.25:
            actions.append("weight_mutation")

        # Always try at least one action
        if not actions:
            actions.append("weight_mutation")

        return actions


class TargetAgent:
    """Generates the candidate hypothesis (weight mutation only)."""

    def __init__(self, use_llm: bool = False, seed: int = 42):
        self.use_llm = use_llm  # kept for API compatibility
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
                0.50,
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


class FeedbackAgent:
    """Evaluates the candidate and decides accept/reject."""

    def __init__(self, brier_df: pd.DataFrame, splits: list[dict[str, Any]]):
        self.brier_df = brier_df
        self.splits = splits

    def evaluate_weight_mutation(self, hyp: Hypothesis) -> dict[str, float]:
        per_split = [evaluate_hypothesis_oos(self.brier_df, s["test_indices"], hyp) for s in self.splits]
        return _mean_stats(per_split)


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
            f"{stats.get('brier_score', 0.25)}\t{stats.get('total_trades', 0)}\t{status}\t{note}\n"
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_sia_hourly(
    use_llm: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """Run one SIA hourly cycle (weight mutation only).

    Returns a summary dict with the cycle's actions and outcomes.
    """
    random.seed(seed)

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
                blend_weight=0.45,
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

    parser = argparse.ArgumentParser(description="SIA hourly weight update loop")
    parser.add_argument("--llm", action="store_true", help="Use LLM (kept for API compat)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    summary = run_sia_hourly(use_llm=args.llm, seed=args.seed)
    print(json.dumps(summary, indent=2, default=str))
