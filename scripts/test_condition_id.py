import sqlite3, json
from executor.bet_placer import BetPlacer
from database.models import Analysis

conn = sqlite3.connect('data/bot.db')
c = conn.cursor()

# Get a market with clob_token_ids
c.execute('SELECT id, city, clob_token_ids FROM weather_markets WHERE clob_token_ids IS NOT NULL AND clob_token_ids != "" LIMIT 1')
r = c.fetchone()
market_id, city, clob_token_ids = r
print(f'Market: {market_id}, City: {city}')

# Parse tokens
tokens = json.loads(clob_token_ids)
print(f'Tokens: {tokens}')

# Create a mock analysis
class MockAnalysis:
    def __init__(self):
        self.recommended_side = "YES"
        self.market_id = market_id

analysis = MockAnalysis()

# Test BetPlacer._resolve_condition_id
placer = BetPlacer()
condition_id = placer._resolve_condition_id(
    type('Market', (), {'raw_data': json.dumps({"clobTokenIds": ["token1", "token2"], "conditionId": "0xtest"})})(),
    analysis
)
print(f'Condition ID from raw_data: {condition_id}')

# Test with market that has clob_token_ids in column
class MockMarket:
    def __init__(self, clob_token_ids):
        self.raw_data = None
        self.clob_token_ids = clob_token_ids

market = MockMarket(clob_token_ids)
condition_id2 = placer._resolve_condition_id(market, analysis)
print(f'Condition ID from clob_token_ids column: {condition_id2}')

conn.close()