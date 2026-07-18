from data_pipeline.unified_datastore import UnifiedDatastore

ds = UnifiedDatastore()
print('Testing build_counterfactual_dataset...')
df = ds.build_counterfactual_dataset()
print(f'Shape: {df.shape}')
if not df.empty:
    print(f'Columns: {list(df.columns)}')
    # Write to file to avoid encoding issues
    with open('counterfactual_output.txt', 'w', encoding='utf-8') as f:
        f.write(f'Shape: {df.shape}\n')
        f.write(f'Columns: {list(df.columns)}\n\n')
        f.write(df[['city','target_date','model_prob','market_price','realized_yes','should_bet','reason']].head(10).to_string())
        f.write('\n\n')
        f.write(f'Realized yes distribution: {df["realized_yes"].value_counts().to_dict()}\n')
        f.write(f'Should bet distribution: {df["should_bet"].value_counts().to_dict()}\n')
        f.write(f'Reason distribution (top 10): {df["reason"].value_counts().head(10).to_dict()}\n')
    print('Output written to counterfactual_output.txt')