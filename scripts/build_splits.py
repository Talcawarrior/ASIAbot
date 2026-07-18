from data_pipeline.unified_datastore import UnifiedDatastore
ds = UnifiedDatastore()
print('Building walk-forward splits...')
splits = ds.build_walk_forward_splits(
    lookback_days=30,
    step_days=7,
    test_days=7,
    date_column='closed_time',
    table_name='markets'
)
print(f'Built {len(splits)} splits')
for s in splits[:5]:
    print(f'  Split {s["split_n"]}: train={s["train_rows"]} rows, test={s["test_rows"]} rows, {s["test_start"]} to {s["test_end"]}')
