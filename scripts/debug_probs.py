"""Debug: check actual prob values vs realized outcomes."""

import pandas as pd
from asi_engine.karpathy_weekly import add_per_model_probabilities, DEFAULT_MODELS
from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier = add_per_model_probabilities(brier, ds=ds)

prob_cols = [f"prob_{m}" for m in DEFAULT_MODELS if f"prob_{m}" in brier.columns]
print(f"Prob columns: {prob_cols}")
print(f"Rows with any prob data: {brier[prob_cols].notna().any(axis=1).sum()}/{len(brier)}")
print()

# Sample: show prob values vs realized
for _, row in brier.head(20).iterrows():
    probs = {m: row.get(f"prob_{m}") for m in DEFAULT_MODELS if f"prob_{m}" in brier.columns}
    avg_prob = sum(v for v in probs.values() if not pd.isna(v)) / max(
        1, sum(1 for v in probs.values() if not pd.isna(v))
    )
    print(
        f"city={row['city']:>15} date={row['target_date']} thresh={row['threshold']:>5.1f} mt={row['market_type']} "
        f"yes_price={row['yes_price']:.3f} realized={row['realized_yes']} "
        f"avg_model_prob={avg_prob:.3f} delta={avg_prob - row['yes_price']:.3f}"
    )

# Distribution of model probabilities
print("\nModel prob distribution:")
for m in DEFAULT_MODELS:
    col = f"prob_{m}"
    if col in brier.columns:
        vals = brier[col].dropna()
        if len(vals) > 0:
            print(
                f"  {m:>25}: n={len(vals):>3} mean={vals.mean():.3f} std={vals.std():.3f} min={vals.min():.3f} max={vals.max():.3f}"
            )
