"""Debug: look at individual trade decisions."""
import math
import pandas as pd
from asi_engine.karpathy_weekly import (
    add_per_model_probabilities,
    _build_splits_from_brier,
    Hypothesis,
    _uniform_weights,
    DEFAULT_MODELS,
    _weighted_mean_prob,
)
from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
brier = ds.build_brier_dataset()
brier = add_per_model_probabilities(brier, ds=ds)
splits = _build_splits_from_brier(brier)

test_df = brier.loc[brier.index.intersection(splits[0]["test_indices"])]
print(f"Test rows: {len(test_df)}")
print(f"Columns: {list(test_df.columns)}")
print()

# Create hypothesis
hyp = Hypothesis(
    description="debug",
    model_weights=_uniform_weights(),
    min_edge=0.01,
    kelly_fraction=0.15,
    max_bet_pct=0.05,
    blend_weight=0.45,
    min_trades=1,
)

# Trace each row
for idx, row in test_df.iterrows():
    yes_prob = _weighted_mean_prob(row, hyp.model_weights, DEFAULT_MODELS)
    if yes_prob is None:
        print(f"Row {idx}: yes_prob=None (missing prob_ cols)")
        continue

    market_price = row.get("yes_price")
    snapshot = row.get("snapshot_yes_price")
    realized = row.get("realized_yes")
    threshold = row.get("threshold")
    mt = row.get("market_type")

    if market_price is None or pd.isna(market_price):
        continue
    if market_price <= 0.01 or market_price >= 0.99:
        continue

    # Blend
    blended = hyp.blend_weight * yes_prob + (1 - hyp.blend_weight) * market_price
    edge = blended - market_price

    if abs(edge) < hyp.min_edge:
        continue

    side = "YES" if edge > 0 else "NO"
    entry = market_price if edge > 0 else 1.0 - market_price
    prob = blended if edge > 0 else 1.0 - blended
    won = (realized >= 0.5) == (edge > 0)

    print(f"Row {idx}: city={row.get('city')}, date={row.get('target_date')}, thresh={threshold:.1f}C, mt={mt}")
    print(f"  model_prob={yes_prob:.4f}, market={market_price:.4f}, blended={blended:.4f}, edge={edge:.4f}")
    print(f"  side={side}, entry={entry:.4f}, prob={prob:.4f}, realized={realized}, won={won}")
    print()
