"""Debug: verify prob_ columns are created correctly."""

import logging
from asi_engine.karpathy_weekly import add_per_model_probabilities, _build_splits_from_brier
from data_pipeline.unified_datastore import UnifiedDatastore

logging.basicConfig(level=logging.INFO)

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
print(f"Before: {brier.shape}, prob_ cols: {[c for c in brier.columns if c.startswith('prob_')]}")

brier2 = add_per_model_probabilities(brier, ds=ds)
prob_cols = [c for c in brier2.columns if c.startswith("prob_")]
print(f"After: {brier2.shape}, prob_ cols: {prob_cols}")

if prob_cols:
    for col in prob_cols:
        nn = brier2[col].notna().sum()
        print(f"  {col}: {nn}/{len(brier2)} non-null")
    print("\nSample rows:")
    print(brier2[prob_cols + ["yes_price", "realized_yes"]].head(5).to_string())
else:
    print("NO PROB COLUMNS CREATED!")
    print("Columns after merge:", list(brier2.columns))

splits = _build_splits_from_brier(brier2)
print(f"\nSplits: {len(splits)}")
for s in splits:
    print(f"  train: {len(s['train_indices'])} test: {len(s['test_indices'])}")
