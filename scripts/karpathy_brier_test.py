"""Real test: evaluate ensemble weight configurations by Brier score on actual outcomes.

This is the honest evaluation — not synthetic market simulation.
Each model predicts temperature, we convert to P(high) via normal CDF,
then compare against realized_yes.
"""

import pandas as pd

from asi_engine.karpathy_weekly import (
    DEFAULT_MODELS,
    _build_splits_from_brier,
    _weighted_mean_prob,
    add_per_model_probabilities,
)
from data_pipeline.unified_datastore import UnifiedDatastore


def evaluate_brier(brier_df, indices, weights):
    """Compute Brier score for given weights on given indices."""
    test = brier_df.loc[brier_df.index.intersection(indices)]
    errors = []
    for _, row in test.iterrows():
        prob = _weighted_mean_prob(row, weights, DEFAULT_MODELS)
        realized = row.get("realized_yes")
        if prob is None or pd.isna(realized):
            continue
        errors.append((prob - float(realized)) ** 2)
    return sum(errors) / len(errors) if errors else 0.25, len(errors)


ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier = add_per_model_probabilities(brier, ds=ds)
splits = _build_splits_from_brier(brier)

print(f"Brier rows: {len(brier)}, splits: {len(splits)}")
print(f"Test rows: {len(splits[0]['test_indices'])}")
print()

# Check how many rows have valid prob data
valid = brier.dropna(subset=[f"prob_{m}" for m in DEFAULT_MODELS if f"prob_{m}" in brier.columns])
print(f"Rows with all prob_ cols: {len(valid)}/{len(brier)}")
print()

# Baseline: uniform weights
uniform = {m: 1.0 / len(DEFAULT_MODELS) for m in DEFAULT_MODELS}

# Test various weight configs
configs = {
    "uniform": uniform,
    "ecmwf_heavy": {
        "gfs_seamless": 0.10,
        "ecmwf_ifs04": 0.35,
        "gem_seamless": 0.10,
        "icon_seamless": 0.15,
        "jma_msm": 0.05,
        "cma_grapes_global": 0.05,
        "ukmo_seamless": 0.05,
        "meteofrance_seamless": 0.15,
    },
    "meteofrance_heavy": {
        "gfs_seamless": 0.10,
        "ecmwf_ifs04": 0.15,
        "gem_seamless": 0.05,
        "icon_seamless": 0.10,
        "jma_msm": 0.05,
        "cma_grapes_global": 0.05,
        "ukmo_seamless": 0.05,
        "meteofrance_seamless": 0.45,
    },
    "best_model_only_meteofrance": {
        "gfs_seamless": 0.0,
        "ecmwf_ifs04": 0.0,
        "gem_seamless": 0.0,
        "icon_seamless": 0.0,
        "jma_msm": 0.0,
        "cma_grapes_global": 0.0,
        "ukmo_seamless": 0.0,
        "meteofrance_seamless": 1.0,
    },
    "best_model_only_ecmwf": {
        "gfs_seamless": 0.0,
        "ecmwf_ifs04": 1.0,
        "gem_seamless": 0.0,
        "icon_seamless": 0.0,
        "jma_msm": 0.0,
        "cma_grapes_global": 0.0,
        "ukmo_seamless": 0.0,
        "meteofrance_seamless": 0.0,
    },
    "inverse_mae_weighted": {
        "gfs_seamless": 0.15,
        "ecmwf_ifs04": 0.25,
        "gem_seamless": 0.10,
        "icon_seamless": 0.15,
        "jma_msm": 0.10,
        "cma_grapes_global": 0.05,
        "ukmo_seamless": 0.10,
        "meteofrance_seamless": 0.10,
    },
}

print(f"{'Config':<30} {'Brier(train)':<15} {'Brier(test)':<15} {'N_train':<10} {'N_test':<10}")
print("-" * 80)

for name, weights in configs.items():
    train_scores = []
    test_scores = []
    for s in splits:
        b_train, n_train = evaluate_brier(brier, s["train_indices"], weights)
        b_test, n_test = evaluate_brier(brier, s["test_indices"], weights)
        train_scores.append(b_train)
        test_scores.append(b_test)
    avg_train = sum(train_scores) / len(train_scores)
    avg_test = sum(test_scores) / len(test_scores)
    print(f"{name:<30} {avg_train:<15.4f} {avg_test:<15.4f} {n_train:<10} {n_test:<10}")

# Also show what the optimal constant prediction would be
p_win = brier["realized_yes"].mean()
const_brier = p_win * (1 - p_win)
print(f"\nOptimal constant prediction ({p_win:.3f}): Brier = {const_brier:.4f}")
