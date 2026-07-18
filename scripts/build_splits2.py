from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
splits = ds.build_walk_forward_splits(
    lookback_days=3, step_days=1, test_days=1, date_column="closed_time", table_name="markets"
)
print(f"Built {len(splits)} splits")
for s in splits[:10]:
    print(
        f"  Split {s['split_n']}: train={s['train_rows']} rows, test={s['test_rows']} rows, {s['test_start']} to {s['test_end']}"
    )
