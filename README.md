# asiabot - Self-Evolving Weather Prediction Bot

**Port: 8091** | **Framework: FastAPI + Next.js** | **Dry-Run Mode: Enabled**

---

## ðŸ“‹ Ä°Ã§indekiler

1. [Sistem Mimarisi](#sistem-mimarisi)
2. [FormÃ¼l & Algoritmalar](#formÃ¼l--algoritmalar)
3. [Veri Pipeline](#veri-pipeline)
4. [Risk YÃ¶netimi](#risk-yÃ¶netimi)
5. [Gas Fee & Slippage](#gas-fee--slippage)
6. [Karpathy-Search ile Strateji Optimizasyonu](#karpathy-search-ile-strateji-optimizasyonu)
7. [Testing Suite](#testing-suite)
8. [Deployment & Deployment YÃ¶netimi](#deployment--deployment-yÃ¶netimi)
9. [API Endpoints](#api-endpoints)
10. [Runbook](#runbook)

---

## ðŸ—ï¸ Sistem Mimarisi

### Genel AkÄ±ÅŸ

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Polymarket      â”‚ â† Fetch Markets
â”‚ Public-Search   â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Weather API     â”‚ â† Open-Meteo (GFS, ECMWF, ICON, JMA, CMA, UKMO, MeteoFrance)
â”‚ Ensemble        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Calculator      â”‚ â† Weighted Mean + StdDev â†’ Probability
â”‚ Engine          â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Strategy        â”‚ â† Kelly Criterion (0.15) + Edge Threshold (5%)
â”‚ Engine          â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Risk Manager    â”‚ â† Exposure Cap, City Cap, Daily Loss Limit
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Betting Engine  â”‚ â† Slippage Adjusted Kelly + Gas Cost
â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚
         â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Settler         â”‚ â† Settlement Logic (won/lost/closed_early)
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### ModÃ¼ller

| ModÃ¼l | Sorumluluk | Dosya |
|-------|-----------|-------|
| **API** | FastAPI endpoints, WebSocket, BotState | `api.py` |
| **Calculator** | OlasÄ±lÄ±k hesaplama, Kelly criterion | `engine/calculator.py` |
| **Strategy** | Edge hesaplama, bet kararÄ± | `engine/strategy.py` |
| **RiskManager** | Exposure cap, city cap | `engine/strategy.py` |
| **BettingEngine** | Bet yerleÅŸtirme, slippage adjustment | `engine/strategy.py` |
| **SettlementEngine** | Settlement hesaplama, PnL | `executor/settler.py` |
| **WeatherEngine** | Multi-model weather fetch | `engine/calculator.py` |
| **PolymarketScraper** | Market fetch & bet placement | `scrapers/polymarket.py` |
| **Database** | SQLite persistence | `database/db.py` |
| **Config** | Configuration management | `config/settings.py` |

### Stack

- **Backend**: FastAPI + Uvicorn + SQLAlchemy
- **Frontend**: Next.js (React) + Tailwind CSS
- **Database**: SQLite (lightweight, local)
- **Weather API**: Open-Meteo (free, no API key)
- **Test Framework**: pytest + pytest-asyncio

---

## ðŸ“ FormÃ¼l & Algoritmalar

### 1. Probability Estimation

**OlasÄ±lÄ±k hesaplama formÃ¼lÃ¼** (weighted mean + stddev):

```python
mean = Î£(weight_i Ã— value_i) / Î£weight_i
std = âˆš[ Î£weight_i Ã— (value_i - mean)Â² / Î£weight_i ]

probability = Î¦(mean, std, threshold, days_ahead, market_type)
```

**Ã–rnek**:
- GFS: 0.7 (weight: 30%)
- ECMWF: 0.65 (weight: 25%)
- ICON: 0.6 (weight: 10%)
- Mean: (0.7Ã—0.3 + 0.65Ã—0.25 + 0.6Ã—0.1) / 0.65 = 0.67
- Threshold: 0.60 (60Â°F)
- Days ahead: 2
- **Probability (HIGH)**: ~72%

### 2. Kelly Criterion

**Kelly fraction hesaplama**:

```python
f* = (p Ã— b - q) / b
```

Where:
- `p` = probability (gÃ¶rsel olasÄ±lÄ±k)
- `b` = odds (price ratio)
- `q` = 1 - p

**Ã–rnek**:
- Probability (p) = 0.65 (65%)
- Entry price = 0.60
- Odds (b) = 1 / 0.60 = 1.67

```python
f* = (0.65 Ã— 1.67 - 0.35) / 1.67
f* = 1.0855 - 0.35 / 1.67
f* = 0.7355 / 1.67
f* = 0.44 (44% Kelly)
```

**asiabot'da** quarter Kelly kullanÄ±lÄ±r (44% Ã— 0.15 = 6.6% of portfolio per bet).

### 3. Max Bet Cap

**Per-bet limit**:

```python
max_bet_cap = portfolio_value Ã— MAX_BET_PCT
```

**Ã–rnek**:
- Portfolio: $1,000
- Max bet %: 0.3%
- **Max bet**: $1000 Ã— 0.003 = **$3.0**

### 4. Max Exposure Cap

**Total exposure limit**:

```python
conservative_portfolio_value = initial_capital + realized_pnl_before_today
max_exposure = conservative_portfolio_value Ã— TOTAL_EXPOSURE_PCT
```

**Ã–rnek**:
- Initial capital: $1,000
- Realized PnL before today: +$50
- Max exposure %: 25%
- **Conservative portfolio**: $1,000 + $50 = $1,050
- **Max exposure**: $1,050 Ã— 0.25 = **$262.5**

**Senaryo 1 - Limit DÄ±ÅŸÄ±**:
- Total open bets: $300
- Max exposure allowed: $262.5
- **Decision**: Reject new bet (exposure cap exceeded)

**Senaryo 2 - Limit Ä°Ã§inde**:
- Total open bets: $200
- Max exposure allowed: $262.5
- **Decision**: Accept bet (exposure = $200 + $3 = $203 â‰¤ $262.5)

### 5. City Cap

**Åžehir bazlÄ± limit**:

```python
total_open_bets_in_city = Î£ bets[city == current_city]
MAX_BETS_PER_CITY = 4

if total_open_bets_in_city >= MAX_BETS_PER_CITY:
    Reject new bet
```

**Ã–rnek**:
- Dallas: 3 bets open
- London: 4 bets open
- Paris: 2 bets open
- **Dallas for next bet**: OK (3 < 4)
- **London for next bet**: REJECT (4 â‰¥ 4)

### 6. Daily Loss Limit

**GÃ¼nlÃ¼k zarar limiti**:

```python
daily_loss_limit_amount = initial_capital Ã— DAILY_LOSS_LIMIT_PCT
realized_daily_loss = Î£(pnl for bets settled today)

if realized_daily_loss >= daily_loss_limit_amount:
    Stop bot or pause new bets
```

**Ã–rnek**:
- Initial capital: $1,000
- Daily loss limit %: 5%
- **Limit**: $1,000 Ã— 0.05 = **$50**

If today's realized PnL = -$50:
- **Action**: Daily loss limit reached (may pause or stop)

### 7. Polymarket Fee

**Official fee formula** (category-specific):

```python
fee = shares Ã— fee_rate Ã— price Ã— (1 - price)
```

**Ã–rnek** (Weather category, fee_rate = 5%):
- Shares: 100
- Price: 0.75
- **Fee**: $100 Ã— 0.05 Ã— 0.75 Ã— (1 - 0.75) = **$0.94**

**Fee is charged at ORDER MATCH TIME**, not at settlement.

### 8. Settlement PnL

**Settlement PnL hesaplama**:

```python
if WON:
    payout = stake / entry_price
    fee_already_paid = shares Ã— fee_rate Ã— price Ã— (1 - price)
    net_pnl = payout - stake - fee_already_paid

if LOST:
    net_pnl = -stake - fee_already_paid
```

**Ã–rnek** (Won bet):
- Stake: $100
- Entry price: 0.60
- Entry fee: $1.50 (calculated beforehand)
- **Payout**: $100 / 0.60 = $166.67
- **Net PnL**: $166.67 - $100 - $1.50 = **$65.17**

**Ã–rnek** (Lost bet):
- Stake: $100
- Entry fee: $1.50
- **Net PnL**: -$100 - $1.50 = **-$101.50**

### 9. Unrealized PnL

**Unrealized PnL hesaplama**:

```python
unrealized_pnl = shares Ã— (current_price - entry_price)
```

**Ã–rnek**:
- Shares: 100
- Entry price: $0.60
- Current price: $0.65
- **Unrealized PnL**: 100 Ã— ($0.65 - $0.60) = **$5.00**

### 10. Win Rate

**Win rate hesaplama**:

```python
win_rate = (wins / total_closed) Ã— 100
```

**Ã–rnek**:
- Wins: 60
- Total closed: 100
- **Win rate**: (60 / 100) Ã— 100 = **60%**

### 11. ROI

**Return on Investment hesaplama**:

```python
roi = (total_pnl / total_stake) Ã— 100
```

**Ã–rnek**:
- Total PnL: $50
- Total stake: $100
- **ROI**: ($50 / $100) Ã— 100 = **50%**

### 12. Exit Price Reconstruction

**Exit price'Ä± PnL'den hesaplama**:

```python
if SIDE == YES:
    exit_price = entry_price Ã— (1 + unrealized_pnl / stake)

if SIDE == NO:
    exit_price = entry_price Ã— (1 - |unrealized_pnl| / stake)
```

**Ã–rnek** (NO side, loss):
- Entry price: $0.60
- Unrealized PnL: -$10
- Stake: $100
- Shares: 166.67
- **Exit price**: 0.60 Ã— (1 - 10/100) = 0.60 Ã— 0.90 = **$0.54**

---

## ðŸ”„ Veri Pipeline

### Pipeline AdÄ±mlarÄ±

1. **Fetch Markets** (Polymarket API)
2. **Parse Markets** (extract parameters)
3. **Weather Forecast** (Open-Meteo ensemble)
4. **Analyze Markets** (calculator â†’ probability â†’ edge)
5. **Risk Check** (exposure cap, city cap, daily loss limit)
6. **Place Bets** (with slippage adjustment)
7. **Settlement** (Polymarket resolves â†’ calculate PnL)

### Veri AkÄ±ÅŸÄ±

```
Polymarket
    â†“
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Weather API â”‚ â† en son 14 gÃ¼n
â”‚ (8 model)   â”‚
â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Weather      â”‚ â† SQLite (weather_forecasts tablosu)
â”‚ Forecasts    â”‚
â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Calculator   â”‚ â† weighted mean + stddev â†’ probability
â”‚ (Analyze)   â”‚
â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Strategy     â”‚ â† Kelly + edge â†’ should_bet?
â”‚ (Betting)   â”‚
â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ API          â”‚ â† REST endpoints (status, markets, signals)
â”‚ /api/*      â”‚
â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜
      â”‚
      â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Dashboard    â”‚ â† Next.js frontend
â”‚ (UI)        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### Database Schemas

#### WeatherMarket
```sql
id           INTEGER PRIMARY KEY
city         TEXT
city_code    TEXT
target_date  TEXT
threshold    REAL (temperature threshold)
metric       TEXT ("temperature_max" | "temperature_min")
yes_price    REAL
no_price     REAL
liquidity    REAL
market_type  TEXT ("HIGH" | "LOW" | "RANGE")
raw_data     TEXT
```

#### WeatherForecast
```sql
id            INTEGER PRIMARY KEY
market_id     INTEGER
city          TEXT
lat           REAL
lon           REAL
target_date   TEXT
metric        TEXT
source        TEXT (model name)
predicted_value REAL
model_weight  REAL
fetched_at    TEXT
```

#### Analysis
```sql
id                INTEGER PRIMARY KEY
market_id         INTEGER
estimated_probability REAL
market_implied_prob REAL
edge              REAL (net edge after slippage + fee)
raw_edge          REAL (theoretical edge)
slippage_pct      REAL
avg_forecast_value REAL
std_forecast_value REAL
num_sources       INTEGER
recommended_side   TEXT ("YES" | "NO")
recommended_amount REAL
confidence_score  REAL
should_bet        BOOLEAN
reason            TEXT
```

#### Bet
```sql
id                    INTEGER PRIMARY KEY
market_id             INTEGER
city                  TEXT
side                  TEXT ("YES" | "NO")
amount                REAL
entry_price           REAL
current_price         REAL
status                TEXT ("placed" | "active" | "settled" | "won" | "lost" | "cancelled")
pnl                   REAL (realized PnL)
unrealized_pnl        REAL
entry_fee             REAL (polymarket fee at bet time)
settled_at            TEXT
closed_at             TEXT
ladder_data           TEXT
```

#### Portfolio
```sql
id                INTEGER PRIMARY KEY
cash_balance      REAL (cash on hand)
initial_value     REAL
current_value     REAL (market value)
total_value       REAL
total_realized_pnl REAL
daily_pnl         REAL
total_won         INTEGER
total_lost        INTEGER
```

---

## âš ï¸ Risk YÃ¶netimi

### Risk Limitleri

| Limit | Value | AÃ§Ä±klama |
|-------|-------|----------|
| **Max bet %** | 0.3% (0.003) | Per-bet limiti |
| **Max exposure %** | 25% (0.25) | Total aÃ§Ä±k pozisyon limiti |
| **City cap** | 4 | Her ÅŸehirde max 4 bet |
| **Daily loss limit %** | 5% (0.05) | GÃ¼nlÃ¼k zarar limiti |
| **Kelly fraction** | 0.15 | Quarter Kelly (0.44 â†’ 0.15) |
| **Min edge** | 5% (0.05) | Minimum net edge (slippage + fee dahil) |
| **Min entry price** | 0.01 | Minimum fiyat (long-shot filtre) |
| **Inefficiency min** | -1.0 | Negatif = gate disabled |

### Risk Check Flow

```
New Bet Decision Flow
    â”‚
    â–¼
1. Check Min Edge
   â”œâ”€â”€ Net edge < 5%? â†’ REJECT
   â”‚
    â–¼
2. Check Min Entry Price
   â”œâ”€â”€ Price < $0.01? â†’ REJECT
   â”‚
    â–¼
3. Check Exposure Cap
   â”œâ”€â”€ Total open + new_bet > Max exposure? â†’ REJECT
   â”‚
    â–¼
4. Check City Cap
   â”œâ”€â”€ Bets in city >= 4? â†’ REJECT
   â”‚
    â–¼
5. Check Daily Loss Limit
   â”œâ”€â”€ Realized loss today >= 5%? â†’ PAUSE/STOP
   â”‚
    â–¼
6. Check Liquidity
   â”œâ”€â”€ Liquidity < threshold? â†’ REJECT
   â”‚
    â–¼
7. Place Bet
   â””â”€â”€ Pass â†’ Place bet with slippage adjustment
```

---

## ðŸ’° Gas Fee & Slippage

### Gas Fee

**Polygon gas fee (per round-trip)**:

```python
gas_cost_usd = $0.10
```

**Cost breakdown**:
- Bet placement: $0.10 gas
- Settlement: $0.10 gas
- Total per cycle: **$0.20**

**Impact on Kelly sizing**:
```python
kelly_raw = raw_kelly_frac Ã— bankroll
gas_cost = kelly_raw Ã— gas_cost_usd
kelly_adj = kelly_raw - gas_cost

if kelly_adj < 1.0:
    Bet size reduced to $1.0 (minimum bet size)
```

**Ã–rnek**:
- Raw Kelly: $6.6 (6.6% of $1,000)
- Gas cost: $6.6 Ã— $0.10 = $0.66
- **Adjusted Kelly**: $6.6 - $0.66 = **$5.94**

### Slippage

**3 slippage modelleri**:

#### 1. Flat Slippage (default for unoptimized)
```python
slippage_pct = strategy.slippage_pct  # 0.5% default

edge = raw_edge - slippage_pct
```

#### 2. Tiered Slippage (optimized)
```python
if entry_price < 0.05:
    slippage_pct = 0.03  # 3%
elif entry_price < 0.10:
    slippage_pct = 0.01  # 1%
else:
    slippage_pct = 0.005  # 0.5%

edge = raw_edge - slippage_pct
```

#### 3. Orderbook Slippage (future, current default: tiered fallback)
```python
condition_id = extract_condition_id_from_raw_data()

if condition_id:
    slippage_pct = estimate_slippage_from_orderbook(condition_id)
else:
    slippage_pct = tiered_slippage(entry_price)
```

**Ã–rnek** (Tiered slippage):
- Entry price: $0.55
- Slippage: **1%** (tiered rule)
- Raw edge: 8%
- **Net edge**: 8% - 1% = **7%** âœ…

**Ã–rnek** (No edge after slippage):
- Entry price: $0.55
- Raw edge: 4%
- Slippage: **1%** (tiered rule)
- **Net edge**: 4% - 1% = **3%** âŒ (< 5% min edge)

### Adjusted Edge Calculation

```python
# Step 1: Raw edge (theoretical)
raw_edge = estimated_probability - market_implied_price

# Step 2: Entry fee
entry_fee = shares Ã— fee_rate Ã— price Ã— (1 - price)

# Step 3: Slippage
slippage_est = estimate_slippage(entry_price)

# Step 4: Gas cost
gas_cost_usd = kelly_raw Ã— gas_cost_per_usd

# Step 5: Adjusted edge
net_edge = raw_edge - slippage - gas_cost
```

---

## ðŸ”¬ Karpathy-Search ile Strateji Optimizasyonu

### Karpathy Arama AlgoritmasÄ±

**Problem**: Naive Kelly bot win rate %94 (62/66 trades) ama kaybeder Ã§Ã¼nkÃ¼:
- Losing trades: Long-shot bets (< 30%)
- Single loss wipes out dozens of small wins

**Ã‡Ã¶zÃ¼m**: Asymmetric-payoff filter (Karpathy search ile bulundu)

### Strateji Parametreleri

| Parametre | Default | Optimized | AÃ§Ä±klama |
|-----------|---------|-----------|----------|
| **min_edge** | 5% | 5% | Minimum net edge |
| **min_entry_price** | 0.01 | 0.35 | Minimum fiyat gate |
| **inefficiency_min** | -1.0 | -0.124 | Asymmetric inefficiency gate |

### min_entry_price (Long-shot filtre)

**Neden gerekli?**
- Low price = Low risk, Low reward
- KarÅŸÄ±lÄ±ksÄ±z risk/Ã¶dÃ¼l asymmetry
- Example: Bet $0.10 for $0.90 profit (90x leverage)

**Ã–rnek**:
- Bet $0.10 â†’ Win $0.90 â†’ Profit $0.80 (800% return)
- Lose bet $0.10 â†’ Loss $0.10 (100% loss)
- **Neden riskli?** Zarar, tek kazananda yÃ¼zlerce kazancÄ±n yanÄ±na sÄ±ÄŸmaz

**Ã–rnek daÄŸÄ±lÄ±m**:
- 62 wins: (10Ã—$0.05) + (20Ã—$0.50) + (20Ã—$1.00) + (12Ã—$5.00) = **$136**
- 4 losses: 4Ã—$0.10 = **$0.40**
- **Net PnL**: $136 - $0.40 - fees = **+$135.60**

Bu Ã¶lÃ§Ã¼de bir asimetriyi dengelemek iÃ§in **min_entry_price = 0.35** filtresi:

- Long-shot bets (< 35%) filtreleniyor
- Sadece "iyi odds" (high payout) bahis kabul ediliyor
- **Trade count**: 66 â†’ ~15 (kazanma oranÄ± %93, ama win/loss balance iyileÅŸti)

### inefficiency_min (Asymmetric gate)

**Konsept**:
- Market inefficiency = Market price â‰  Fair value
- Asymmetric inefficiency = One direction more mispriced than other

**Ã–rnek**:
```
Market: "Temperature will exceed 80Â°F in Dallas"
Current price: YES = 0.60, NO = 0.40
Fair value (ensemble): YES = 0.55, NO = 0.45

Inefficiency (YES):
  0.55 - 0.60 = -0.05 (overpriced, avoid)

Inefficiency (NO):
  0.45 - 0.40 = +0.05 (underpriced, bet!)

Required inefficiency: -0.124 (we want NO to be MORE underpriced)
```

**Karpatzy sonucu**:
- `inefficiency_min = -0.124` vermiÅŸ en iyi trade-off
- Negatif deÄŸer = market'in YES tarafÄ±nÄ± overprice etmesi gerekiyor (NO tarafÄ±nÄ± bet et)

---

## ðŸ§ª Testing Suite

### ðŸ“Š KapsamlÄ± Test Ã–zeti

| Test Kategorisi | Test SayÄ±sÄ± | BaÅŸarÄ± OranÄ± |
|---|---|---|
| **AI Model Testleri** | 8 | 100% |
| **FormÃ¼l Testleri** | 12 | 100% |
| **UI Testleri** | 6 | 100% |
| **API Endpoint Testleri** | 15 | 100% |
| **Data Pipeline Testleri** | 10 | 100% |
| **Risk YÃ¶netimi Testleri** | 9 | 100% |
| **End-to-End Testleri** | 6 | 100% |
| **Toplam** | **66** | **100%** |

**Test Raporu**: [SYSTEM_TESTING_REPORT.md](./SYSTEM_TESTING_REPORT.md) â€” DetaylÄ± test sonuÃ§larÄ±, formÃ¼l doÄŸrulamalarÄ± ve performans metrikleri.

---

### Unit Testler

**Test dosyasÄ±**: `tests/test_units.py`

**Test kategorileri**:

| Test SÄ±nÄ±fÄ± | Test SayÄ±sÄ± | Ã–zet |
|-------------|------------|------|
| `TestCalculatorEstimateProbability` | 8 | OlasÄ±lÄ±k hesaplama |
| `TestCalculatorKellyCriterion` | 4 | Kelly criterion |
| `TestMaxBetCap` | 3 | Max bet cap |
| `TestMaxExposureCap` | 3 | Max exposure cap |
| `TestPolymarketFee` | 4 | Fee hesaplama |
| `TestSettlementPnL` | 3 | Settlement PnL |
| `TestPortfolioValues` | 7 | Portfolio hesaplamalarÄ± |
| `TestSlippageModels` | 4 | Slippage modelleri |
| `TestStrategyParams` | 3 | Karpathy search params |

**Test run**:
```bash
cd asiabot
pytest tests/test_units.py -v
```

---

### YENÄ°: KapsamlÄ± Test Seti

**Test dosyasÄ±**: `tests/test_comprehensive.py` âœ¨

66 test kapsayan kapsamlÄ± test seti:
- **AI Model**: Semua agent, Karpathy search (grid optimization, performance, cache)
- **FormÃ¼lller**: Polymarket fee (resmi dokÃ¼mantasyon %100 uyum), Gas fee, Slippage (3 model), Kelly criterion
- **UI**: Dashboard, YES/NO butonlarÄ±, WebSocket gÃ¼ncellemeleri
- **API**: Health check (22 metric), Portfolio, Markets (formÃ¼l ile hesaplama)
- **Data Pipeline**: Weather ensemble (8 model, 1,260 veri), Polymarket ingest, Walk-forward OOS split
- **Risk**: City cap, max exposure, stop-loss
- **E2E**: Mock E2E, Historical calibrations backtest

**Test run**:
```bash
cd asiabot
pytest tests/test_comprehensive.py -v
```

---

### Integration Testler

**Test dosyasÄ±**: `tests/test_integration.py`

**Test kategorileri**:

| Test SÄ±nÄ±fÄ± | Test SayÄ±sÄ± | Ã–zet |
|-------------|------------|------|
| `TestBotStartup` | 3 | Bot baÅŸlatma |
| `TestDataPipeline` | 4 | Veri pipeline |
| `TestAPIEndpoints` | 7 | API endpoints |
| `TestASIEvolveEndpoints` | 3 | ASI-Evolve endpoints |
| `TestUIComponents` | 3 | UI components |
| `TestRiskManagement` | 4 | Risk yÃ¶netimi |

**Test run**:
```bash
cd asiabot
pytest tests/test_integration.py -v
```

### Test Runner Script

**TÃ¼m testleri Ã§alÄ±ÅŸtÄ±r**:
```bash
python run_tests.py
```

**Ã–zel testler**:
```bash
python run_tests.py --unit
python run_tests.py --integration
python run_tests.py -v --unit --integration
python run_tests.py --no-unit --integration
```

### Test Coverage

**Åžu anki coverage** (estimated):
- **Calculator**: ~90%
- **Formulas**: 100%
- **API endpoints**: ~70%
- **Strategy**: ~80%
- **Slippage & Gas fee**: ~50%

**Teste dayalÄ± geliÅŸtirme (TDD)**:
1. Unit test yaz
2. Unit test run â†’ fail
3. Implement kod
4. Unit test run â†’ pass
5. Integration test
6. Code review

---

## ðŸš€ Deployment & Deployment YÃ¶netimi

### Local Development

**BaÅŸlatma**:
```bash
cd asiabot

# Install dependencies
pip install -r requirements.txt

# Database init
python main.py reset  # (optional, resets DB)

# Start bot
python main.py bot  # (foreground, port 8091)

# Alternative: API only
python main.py run
```

**API endpoints**:
```
GET  /api/status          â†’ Bot status & portfolio
GET  /api/markets         â†’ Open + missed markets
GET  /api/signals         â†’ Active bets
GET  /api/history         â†’ Settled bets
GET  /api/equity-curve    â†’ Daily PnL
GET  /api/slippage        â†’ Slippage data
GET  /api/health-check    â†’ Bot health metrics
POST /api/start           â†’ Start bot loops
POST /api/stop            â†’ Stop bot loops
POST /api/reset           â†’ Reset bot state
```

**Dashboard**:
```
http://127.0.0.1:8091
```

### Production Deployment

**Ã–nerilen stack**:
- Backend: FastAPI + Gunicorn + Uvicorn workers
- Database: PostgreSQL (instead of SQLite)
- Reverse Proxy: Nginx
- SSL: Let's Encrypt (certbot)

**Deploy steps**:
```bash
# 1. Copy to production server
scp -r asiabot user@server:/opt/asiabot

# 2. Install dependencies
pip install -r requirements.txt
cd asiabot
pip install gunicorn uvicorn workers

# 3. Set environment variables
export asiabot_API_KEY="your_api_key"
export DRY_RUN="false"
export MAX_BET_PCT="0.001"  # 0.1% (decrease risk)

# 4. Start bot
gunicorn api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8091

# 5. Systemd service (recommended)
cat > /etc/systemd/system/asiabot.service <<EOF
[Unit]
Description=asiabot Bot
After=network.target

[Service]
Type=simple
User=asiabot
WorkingDirectory=/opt/asiabot
Environment="PATH=/opt/asiabot/venv/bin"
ExecStart=/opt/asiabot/venv/bin/gunicorn api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8091
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start asiabot
systemctl enable asiabot
```

**Nginx config**:
```nginx
server {
    listen 80;
    server_name asiabot.example.com;

    location / {
        proxy_pass http://127.0.0.1:8091;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static {
        alias /opt/asiabot/dashboard/out;
    }
}
```

### Monitoring & Logging

**Health check**:
```bash
curl http://127.0.0.1:8091/api/health-check
```

**Status check**:
```bash
curl http://127.0.0.1:8091/api/status | jq
```

**Logs**:
```bash
# Backend logs
tail -f logs/bot.log

# Systemd logs
journalctl -u asiabot -f
```

**Alerts** (recommended):
- Daily loss > 5% â†’ Slack alert
- Exposure > 90% â†’ Critical alert
- API down â†’ Slack alert
- Database connection error â†’ Alert

### Backup & Restore

**Database backup**:
```bash
# Backup
cp data/bot.db data/bot.db.backup.$(date +%Y%m%d)

# Restore
cp data/bot.db.backup.20240615 data/bot.db
```

**Config backup**:
```bash
cp config/settings.py config/settings.py.backup
```

---

## ðŸ”Œ API Endpoints

### GET /api/status

**Response**:
```json
{
  "is_running": true,
  "locked": false,
  "portfolio": {
    "initial": 1000.0,
    "current": 1050.0,
    "daily_pnl": 50.0,
    "daily_roi": 5.0,
    "unrealized_pnl": 30.0,
    "realized_pnl": 20.0,
    "total_pnl": 50.0,
    "total_roi": 5.0,
    "exposure": 200.0,
    "max_exposure": 262.5
  },
  "stats": {
    "total_signals": 100,
    "total_bets": 10,
    "win_count": 55,
    "loss_count": 45,
    "total_closed": 100,
    "last_scan": "2024-06-15T10:30:00Z"
  },
  "limits": {
    "max_bet_pct": 0.3,
    "max_exposure_pct": 25.0,
    "daily_stop_loss_pct": 5.0,
    "city_cap": 4
  },
  "metrics": {
    "sharpe_ratio": 0.45,
    "max_drawdown_pct": 2.5
  },
  "open_positions": [
    {
      "id": "123",
      "city": "Dallas",
      "side": "YES",
      "entry_price": 0.55,
      "current_price": 0.57,
      "unrealized_pnl": 0.6,
      "edge": 8.0,
      "shares": 6.0,
      "amount": 3.0
    }
  ]
}
```

### GET /api/markets

**Response**:
```json
{
  "markets": [
    {
      "id": "123",
      "city": "Dallas",
      "city_code": "SIGNAL",
      "date": "2024-06-17T00:00:00Z",
      "outcome_type": "YES",
      "strike_temp": 80.0,
      "current_yes_bid": 0.55,
      "current_no_bid": 0.45,
      "model_prob": 0.72,
      "edge": 0.17,
      "ev": 0.099,
      "status": "REJECTED (Risk Cap)"
    }
  ],
  "count": 1
}
```

### GET /api/signals

**Response**:
```json
{
  "signals": [
    {
      "id": "456",
      "market_id": "456",
      "city": "London",
      "outcome": "YES",
      "entry_price": 0.5,
      "current_price": 0.52,
      "stake_amount": 3.0,
      "unrealized_pnl": 0.6,
      "fair_value": 0.65,
      "edge": 0.13,
      "ladder_orders": [],
      "status": "active"
    }
  ],
  "count": 1
}
```

### GET /api/history

**Response**:
```json
{
  "history": [
    {
      "id": 100,
      "city": "Paris",
      "outcome": "YES",
      "entry_price": 0.6,
      "stake_amount": 3.0,
      "realized_pnl": 1.5,
      "roi": 50.0,
      "edge": 10.0,
      "result": "WIN",
      "placed_at": "2024-06-14T10:00:00Z",
      "settled_at": "2024-06-15T00:00:00Z",
      "exit_type": "ST"
    }
  ],
  "stats": {
    "total_won": 55,
    "total_lost": 45,
    "total_closed_early": 0,
    "win_rate": 55.0,
    "overall_roi": 25.0,
    "total_stake": 300.0,
    "total_pnl": 75.0,
    "profit_factor": 2.5
  }
}
```

---

## ðŸ“– Runbook

### Startup Checklist

- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Database initialized: `python main.py reset`
- [ ] Environment variables set (`.env` file)
- [ ] Config values verified in `config/settings.py`
- [ ] API key set: `export asiabot_API_KEY="your_key"`

### Daily Operations

1. **Check bot status**:
   ```bash
   curl http://127.0.0.1:8091/api/status | jq
   ```

2. **Check open positions**:
   ```bash
   curl http://127.0.0.1:8091/api/signals | jq '.signals[] | {city, side, edge, unrealized_pnl}'
   ```

3. **Check health metrics**:
   ```bash
   curl http://127.0.0.1:8091/api/health-check | jq '.red_flags'
   ```

4. **View logs**:
   ```bash
   tail -f logs/bot.log
   ```

### Troubleshooting

**Bot doesn't respond**:
```bash
# Check if port is in use
netstat -ano | findstr 8091

# Check if process is running
tasklist | findstr python

# Restart bot
python main.py bot
```

**Too many rejected bets**:
- Check `min_edge` threshold
- Check `inefficiency_min` gate
- Verify weather API connectivity
- Check historical calibrations

**Exposure cap exceeded**:
- Reduce `MAX_BET_PCT`
- Close some open positions
- Reduce `TOTAL_EXPOSURE_PCT`

**High slippage**:
- Check `min_entry_price` threshold
- Verify orderbook slippage model
- Reduce bet sizes

**Gas fee too high**:
- Reduce `gas_cost_usd` (temporarily)
- Increase `KELLY_FRACTION` (slower withdrawal)
- Switch to schedule optimization

### Emergency Stops

**Stop bot immediately**:
```bash
curl -X POST http://127.0.0.1:8091/api/stop
```

**Reset bot (all data lost)**:
```bash
curl -X POST http://127.0.0.1:8091/api/reset
```

**Emergency database backup**:
```bash
cp data/bot.db data/bot.db.emergency.backup
```

---

## ðŸ“Š Performance Metrics

### Sample Data (90 days, 15 cities)

| Metric | Value |
|--------|-------|
| **Total signals analyzed** | 1,500+ |
| **Total bets placed** | 120+ |
| **Win rate** | ~55% |
| **Avg edge** | 5-8% |
| **Sharpe ratio** | 0.4-0.6 |
| **Max drawdown** | 2-3% |
| **Daily loss limit hits** | 1-2 times/month |

### Per-Metric Breakdown

**Signals by city** (top 5):
- London: 200 signals
- Paris: 180 signals
- Berlin: 150 signals
- Tokyo: 140 signals
- Seoul: 120 signals

**Signals by model**:
- GFS: 30% weight, 450 signals
- ECMWF: 25% weight, 375 signals
- ICON: 10% weight, 150 signals
- JMA: 8% weight, 120 signals
- CMA: 5% weight, 75 signals

**Bets by outcome**:
- YES: 65 bets (54%)
- NO: 55 bets (46%)

**Bets by edge bin**:
- 10-15% edge: 30 bets (25%)
- 7-10% edge: 50 bets (42%)
- 5-7% edge: 40 bets (33%)
- <5% edge: 0 bets (rejected)

---

## ðŸ”® ASI-Evolve Dashboard

### Weights (Self-Evolving)

| Model | Weight | Brier Score | Accuracy | Num Predictions |
|-------|--------|-------------|----------|-----------------|
| gfs_seamless | 0.30 | 0.12 | 65% | 450 |
| ecmwf_ifs025 | 0.25 | 0.10 | 68% | 375 |
| icon_global | 0.10 | 0.15 | 62% | 150 |
| jma_seamless | 0.08 | 0.08 | 72% | 120 |
| meteofrance_seamless | 0.03 | 0.10 | 65% | 45 |

### Cognition Base Insights

**Example insight**:
- "London temperature markets show 5% positive bias in July"
- "ECMWF performs better for 2-day-ahead markets"
- "Threshold-based markets have higher edge variance"

### Auto-Evolve

**Triggers**:
- Every 24 hours
- If cumulative edge < 3% for 7 days
- If certain model underperforms by > 10%

**Algorithm**:
1. Recalculate weights based on model accuracy
2. Update `strategy_params.json`
3. Apply new weights (next bet cycle)
4. Log weight changes

---

## ðŸ“ž Support & Documentation

- **GitHub**: https://github.com/Talcawarrior/asiabot
- **Issues**: Report bugs on GitHub
- **Documentation**: This file + inline code comments

---

**Last updated**: 2026-07-15
**Version**: 1.0.0
**Status**: Production-ready (dry-run mode)

