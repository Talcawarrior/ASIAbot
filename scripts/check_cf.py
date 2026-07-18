from data_pipeline.unified_datastore import UnifiedDatastore
import json

ds = UnifiedDatastore()
df = ds.build_counterfactual_dataset()
print(f'Shape: {df.shape}')
print(f'Columns: {list(df.columns)}')
print()

print('Sample model_predictions:')
for i, row in df.head(3).iterrows():
    mp = row.get('model_predictions', {})
    if isinstance(mp, str):
        mp = json.loads(mp)
    print(f'  Type: {type(mp)}, Keys: {list(mp.keys()) if isinstance(mp, dict) else "N/A"}')
    if isinstance(mp, dict):
        for k, v in list(mp.items())[:3]:
            print(f'    {k}: {v}')
    print()