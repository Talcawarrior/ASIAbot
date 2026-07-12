"""Quick Karpathy test with lower min_edge to generate more trades."""

import logging
from asi_engine.karpathy_weekly import (
    _build_splits_from_brier,
    add_per_model_probabilities,
    evaluate_hypothesis_oos,
    Hypothesis,
    _uniform_weights,
)
from data_pipeline.unified_datastore import UnifiedDatastore

logging.basicConfig(level=logging.WARNING)

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier = add_per_model_probabilities(brier, ds=ds)

# Build splits
splits = _build_splits_from_brier(brier)
print(f"Brier rows: {len(brier)}, splits: {len(splits)}")

# Test different min_edge values
for min_edge in [0.01, 0.02, 0.03, 0.05, 0.07, 0.10]:
    hyp = Hypothesis(
        description=f"test edge={min_edge}",
        model_weights=_uniform_weights(),
        min_edge=min_edge,
        kelly_fraction=0.15,
        max_bet_pct=0.05,
        blend_weight=0.45,
        min_trades=1,
    )
    per_split = [evaluate_hypothesis_oos(brier, s["test_indices"], hyp) for s in splits]
    total_trades = sum(s["total_trades"] for s in per_split)
    total_pnl = sum(s["total_pnl"] for s in per_split)
    avg_sharpe = sum(s["sharpe"] for s in per_split) / len(per_split) if per_split else 0
    avg_brier = sum(s["brier_score"] for s in per_split) / len(per_split) if per_split else 0
    avg_roi = sum(s["roi_pct"] for s in per_split) / len(per_split) if per_split else 0
    print(
        f"  min_edge={min_edge:.2f}: trades={total_trades}, "
        f"pnl=${total_pnl:.2f}, sharpe={avg_sharpe:.3f}, "
        f"brier={avg_brier:.4f}, roi={avg_roi:.2f}%"
    )
