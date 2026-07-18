import requests
import json

# Try CLOB API for historical trades
url = 'https://clob.polymarket.com/trades'
params = {
    'limit': 100,
    'offset': 0
}

response = requests.get(url, params=params)
print(f'CLOB trades status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Trades: {len(data)}')
    if data:
        print(json.dumps(data[0], indent=2))