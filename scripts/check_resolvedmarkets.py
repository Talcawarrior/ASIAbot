import requests
import json

# Try ResolvedMarkets API
url = 'https://resolvedmarkets.polymarket.com/markets'
params = {
    'limit': 100,
    'offset': 0
}

response = requests.get(url, params=params)
print(f'ResolvedMarkets status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Markets: {len(data)}')
    if data:
        print(json.dumps(data[0], indent=2))