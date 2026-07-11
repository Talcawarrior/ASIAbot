# ASIAbot — Polymarket Weather Prediction Trading Bot

**Complete Technical Documentation** — All features, calculations, data sources, limits, AI layers, and risk protections.

---

## 1. Overview

| Property | Value |
|----------|-------|
| **Project** | ASIAbot — Automated weather market trader on Polymarket |
| **Stack** | Python 3.12, FastAPI, SQLAlchemy, aiohttp, pandas |
| **Port** | 8091 (HTTP + WebSocket) |
| **Mode** | Paper trading (DRY_RUN=true enforced) |
| **Database** | SQLite (`data/bot.db`) |
| **Entry Point** | `python main.py bot` |

**Core Loop:**
```
scan_and_bet_loop (every 5 min, 60s after midnight)
    ├─ fetch_markets()        → Polymarket Gamma API
    ├─ parse_markets()        → filter weather markets, extract city/date/threshold
    ├─ fetch_weather()        → Open-Meteo (8 models) + WeatherAPI
    └─ run_cycle()            → analyze → decide → place bets → risk checks

settlement_loop (every 2 min)
    ├─ settle_all()           → Gamma API resolution
    ├─ early_exit_check()     → stop-loss / take-profit / trailing / time decay
    ├─ rebalance_check()      → close loser, open better edge
    └─ SIA optimization       → hourly weight + harness update
```

---

## 2. Configuration (Single Source of Truth)

**File:** `config/settings.py` → `bot_config` (BotConfig dataclass)

### 2.1 StrategyConfig (Trading Parameters)

| Parameter | Default | Source | Description |
|-----------|---------|--------|-------------|
| `min_edge` | **0.05** (5%) | `.env` / `strategy_params.json` | Minimum net edge after slippage+fees to place bet |
| `kelly_fraction` | **0.15** (15%) | `.env` / `strategy_params.json` | Quarter-Kelly sizing multiplier |
| `max_bet_pct` | **0.006** (0.6%) | `.env` ONLY | Max single bet as % of portfolio |
| `blend_weight` | **0.45** | `strategy_params.json` | Model vs market probability blend (0.35–0.50 clamp) |
| `min_entry_price` | 0.01 (clamped to 0.05) | `strategy_params.json` | Reject long-shot markets below this price |
| `inefficiency_min` | -1.0 (disabled) | `strategy_params.json` | Market mispricing gate (negative = disabled) |
| `min_yes_prob` | 0.15 | `.env` | Model probability floor for YES bets |
| `min_sources` | 2 | code | Minimum forecast sources required |
| `min_days_ahead` | 1 | code | Reject same-day markets |
| `max_days_ahead` | 2 | code | Only trade 1-2 day ahead markets |
| `fee_drag` | 0.05 (5%) | code | Polymarket taker fee |
| `slippage_model` | "orderbook" | code | "flat" / "tiered" / "orderbook" |
| `flat_bet_usd` | 0.0 | `.env` | 0 = Kelly sizing, >0 = fixed $ per bet |
| `daily_loss_limit` | 0.20 (20%) | `.env` | Circuit breaker: stop all trading if hit |

### 2.2 RiskConfig (Active Risk Management)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `stop_loss_pct` | 0.20 (20%) | Auto-close if position down 20% |
| `take_profit_pct` | 0.80 (80%) | Auto-close if position up 80% |
| `trailing_stop_pct` | 0.15 (15%) | Trail from peak, close on 15% drop |
| `time_decay_hours` | 24 | Hours before settlement to check |
| `time_decay_threshold` | -0.10 | Close if down 10% within time_decay_hours |
| `min_rebalance_edge_ratio` | 2.0 | New edge must be ≥2× old edge to rebalance |
| `rebalance_min_loss` | -0.15 | Only rebalance positions down ≥15% |

### 2.3 Hard Safety Clamps (Non-Overridable)

Applied in `apply_persisted_strategy_params()` at import:

```python
MIN_EDGE_FLOOR = 0.05           # Never below 5% (breakeven after 5% fee + slippage)
KELLY_FRACTION_MIN = 0.05       # Below = meaningless sizing
KELLY_FRACTION_MAX = 0.25       # Above = too aggressive
MIN_ENTRY_PRICE_FLOOR = 0.05    # Long-shot markets bleed asymmetrically
INEFFICIENCY_MIN_FLOOR = -0.20  # More negative = noise
BLEND_WEIGHT_MIN = 0.35         # Mostly market anchor
BLEND_WEIGHT_MAX = 0.50         # CRITICAL: Never pure-model (triggers NO bias)
```

### 2.4 Model Weights (Default + SIA Overlay)

| Model | Default Weight | Source |
|-------|---------------|--------|
| `gfs_seamless` | 0.30 | NWS GFS |
| `ecmwf_ifs025` | 0.25 | ECMWF IFS |
| `gem_global` | 0.15 | CMC GEM |
| `icon_global` | 0.10 | DWD ICON |
| `jma_seamless` | 0.08 | JMA |
| `cma_grapes_global` | 0.05 | CMA GRAPES |
| `ukmo_seamless` | 0.04 | UK Met Office |
| `meteofrance_seamless` | 0.03 | Météo-France |

**SIA hourly updates** overlay persisted weights from `data/model_weights.json`.

### 2.5 City Coverage (85 Cities)

Coordinates mapped via ICAO codes in `_ICAO_COORDS` (85 entries):
- **Turkey:** 4 (Ankara, Istanbul, Izmir, Antalya)
- **USA:** 15 (Dallas, Miami, Chicago, NYC, LA, Vegas, Phoenix, Houston, Atlanta, Boston, Seattle, Denver, DC, SF, Orlando)
- **Canada/Mexico:** 5
- **South America:** 5
- **Europe:** 26
- **Middle East:** 4
- **Asia:** 22
- **Oceania:** 4
- **Africa:** 2

---

## 3. Data Pipeline

### 3.1 Market Discovery (`scrapers/polymarket.py`)

- **Source:** `https://gamma-api.polymarket.com/markets`
- **Filter:** `weather_keywords` = ["temperature", "temp ", "°c", "°f", "celsius", "fahrenheit", "highest", "lowest", "warmest", "coldest"]
- **Output:** `WeatherMarket` rows with `city`, `target_date`, `threshold`, `metric` (temperature_max/min), `yes_price`, `no_price`, `condition_id`, `tokens`

### 3.2 Weather Forecasting (`scrapers/meteo.py`)

**MeteoFetcher.fetch_all_markets()** — Parallel fetch for 65+ city/date groups:

```
1. Query open markets → group by (lat, lon, target_date)
2. For each group (async, semaphore=20, throttle=1s):
   a. Try Ensemble (8-model Open-Meteo) → get_multi_model_forecast()
   b. Fallback: DB cache (replicate existing forecasts)
   c. Fallback: Backup sources (Open-Meteo single + WeatherAPI)
3. Persist to WeatherForecast table
```

**Sources:**
- **Open-Meteo** (free, no key): 8 global models, 14-day forecast, `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`
- **WeatherAPI.com** (needs key): Backup, single model

**Cache:** In-process dict with TTL
- Success: 30 minutes
- Failure: 5 minutes
- Key: `(lat, lon, target_date, source)`

**Throttle:** Per-host, default 6s (`OPEN_METEO_MIN_INTERVAL_S` env)

**BUG FIXES Applied:**
- BUG-1: No shared SQLAlchemy session across async tasks (each task gets fresh session)
- BUG-2: Sync `fetch_for_markets()` wrapped in `asyncio.to_thread()`
- BUG-4: Removed `asyncio.set_event_loop()` in worker thread

### 3.3 Ensemble Forecast (`engine/calculator.py` → `WeatherEngine.get_multi_model_forecast()`)

```
1. Check in-memory cache (_forecast_cache keyed by city coords)
2. Check DB cache (existing WeatherForecast rows for this city/date)
3. Call Open-Meteo API with `models=gfs_seamless,ecmwf_ifs025,gem_global,icon_global,jma_seamless,cma_grapes_global,ukmo_seamless,meteofrance_seamless`
4. Apply CalibrationEngine bias correction (MBE per model per city)
5. Compute weighted mean/std using model_weights
6. Persist BOTH temperature_max AND temperature_min to DB (single API call)
7. Return {weighted_mean, weighted_std, model_count, model_temps, timestamp}
```

**CalibrationEngine:** Loads `data/asi_calibration.json` (per-model MBE from settled markets). Applies: `calibrated_temp = raw_temp - bias`.

**BUG-3 FIX:** Global 429 cooldown (`_global_429_until`) — one 429 cools down entire batch for 30s, max 2 retries × 15s = 30s worst case per city (was 227 min exponential backoff).

---

## 4. Probability & Edge Calculation

### 4.1 Core Function: `utils.probability.estimate_probability()`

```python
estimate_probability(
    mean: float,           # Weighted mean forecast temperature
    std: float,            # Weighted std (inter-model spread)
    threshold: float,      # Market strike temperature
    days_ahead: int,       # Days until resolution
    market_type: str,      # "HIGH" | "LOW" | "RANGE"
    range_low: float,      # For RANGE markets
    range_high: float      # For RANGE markets
) -> float                 # P(YES)
```

**Market Types:**
- **HIGH** (YES = temp ≥ threshold): `P = 1 - CDF((threshold - mean) / σ)`
- **LOW** (YES = temp ≤ threshold): `P = CDF((threshold - mean) / σ)`
- **RANGE** (YES = temp in [low, high]): `P = CDF((high - mean)/σ) - CDF((low - mean)/σ)`

**Uncertainty Scaling:** `total_std = sqrt(std² + (days_ahead × 0.5)²)`, minimum **1.5°C** (not 1.0°C). This is RSS (root-sum-square) combination, not additive.

**CDF:** SciPy `norm.cdf` if available, else Abramowitz & Stegun approximation (1e-7 accuracy).

### 4.2 Per-Model Probabilities (for SIA)

For each model's raw temperature: `model_prob = estimate_probability(model_temp, total_std, threshold, days_ahead, market_type)`

Stored in `Analysis.model_predictions` JSON for SIA weight optimization.

### 4.3 Blended Probability (Market Anchor)

```python
bw = bot_config.strategy.blend_weight  # 0.45 default, clamped [0.35, 0.50]
if 0.01 < market_price < 0.99:
    blended_prob = bw * model_prob + (1 - bw) * market_price
else:
    blended_prob = model_prob
```

**Why clamp at 0.50?** Pure model (bw=1.0) triggers systematic NO bias on low-price markets. Market anchor prevents this.

### 4.4 Edge Calculation

```python
raw_edge = blended_prob - market_price  # YES edge
if raw_edge <= 0:
    # Check NO side
    no_prob = 1 - blended_prob
    no_implied = market.no_price or (1 - market_price)
    no_edge = no_prob - no_implied
    if no_edge > 0:
        raw_edge = no_edge
        side = "NO"
```

### 4.5 Net Edge (After Costs)

```python
# Slippage estimation (orderbook-aware)
slippage_est = estimate_slippage(entry_price, condition_id)
# Returns: slippage_pct, model_used ("orderbook"|"tiered"|"flat")

# Fee drag
fee_drag = 0.05  # 5% Polymarket taker fee

# Gas cost
gas_cost_usd = 0.10  # Polygon round-trip

# Net edge = raw_edge - slippage_pct - fee_drag - (gas_cost / bet_amount)
net_edge = adjust_edge_for_costs(raw_edge, entry_price, bet_amount_usd=bet_amount)
```

### 4.6 Kelly Sizing

```python
# utils/kelly.py
def kelly_bet_amount(bankroll, model_prob, market_price, fraction=0.15, min_bet=1.0, max_bet_pct=0.03, edge=None):
    f_star = (model_prob * (1 - market_price) - (1 - model_prob) * market_price) / (1 - market_price)
    
    # EV FIX: If edge provided, use dynamic sizing
    if edge is not None and edge > 0:
        fraction = dynamic_kelly_fraction(edge, fraction)      # 0.10/0.15/0.25 by edge band
        max_bet_pct = dynamic_max_bet_pct(edge, max_bet_pct)   # 0.02/0.03/0.05 by edge band
    
    kelly_raw = f_star * fraction * bankroll
    
    # EV FIX: min_bet floor only applies if Kelly is close to min_bet
    # If Kelly < min_bet/2 → return 0 (don't bet), else floor at min_bet
    if kelly_raw < min_bet * 0.5:
        return 0.0
    amount = max(kelly_raw, min_bet)
    
    capped = min(amount, max_bet_cap(conservative_value, max_bet_pct))
    final = adjust_kelly_for_slippage(capped, entry_price)
    return round(final, 2)
```

**Note:** Default `max_bet_pct=0.03` in function signature, but all callers explicitly pass `max_bet_pct=self.config.MAX_BET_PCT` (0.006 from .env). The dynamic sizing overrides this based on edge bands.

---

## 5. Bet Decision Gates (All Must Pass)

In `executor/bet_placer.py` → `BetDecision` gate system:

| Gate | Check | Failure Action |
|------|-------|----------------|
| `analysis_exists` | Analysis exists AND `should_bet=True` | Skip |
| `edge_positive` | `net_edge >= effective_min_edge` | Skip |
| `market_exists` | Market row exists in DB | Skip |
| `circuit_breaker` | Daily PnL > -20% of portfolio | **HALT ALL TRADING** |
| `city_cap` | Bets in this city < 4 | Skip |
| `exposure_cap` | Total exposure < 25% of portfolio | Skip |
| `price_valid` | `is_valid_binary_price(yes, no)` | Skip |
| `min_entry_price` | Market price ≥ 0.05 | Skip |
| `min_yes_prob` | Model prob ≥ 0.15 (for YES bets) | Skip |
| `inefficiency` | `abs(raw_edge) >= inefficiency_min` | Skip |
| `days_ahead` | 1 ≤ days_ahead ≤ 2 | Skip |
| `liquidity_ok` | Always true (min_liquidity=0) | — |
| `bet_amount` | `recommended_amount > $1` | Skip |

**Effective Min Edge (Time-to-Close Scaling + High-Uncertainty Guard):**
```python
# utils/probability.compute_effective_min_edge()
base = bot_config.strategy.min_edge  # 0.05

# HIGH-UNCERTAINTY GUARD: if inter-model spread > 2.5°C, double min_edge
if std is not None and std > 2.5:
    base = base * 2.0  # 0.10 for RANGE/high-spread markets

# Time-to-close ramp: 1× at 24h before close → 2× at 0h
hours_left = (resolution - now).total_seconds() / 3600
if hours_left >= edge_escalation_hours:  # 24h
    return base
if hours_left <= 0:
    return base * edge_escalation_multiplier  # 2.0
fraction = hours_left / edge_escalation_hours
return base * (1.0 + (edge_escalation_multiplier - 1.0) * (1.0 - fraction))
```

---

## 6. Active Risk Management (Position-Level)

**File:** `executor/settler.py` → `SettlementEngine` + `RiskManager`

### 6.1 Early Exit Triggers (Checked Every Settlement Cycle ~2 min)

| Trigger | Condition | Action |
|---------|-----------|--------|
| **Stop-Loss** | Unrealized PnL ≤ -20% | Close position immediately |
| **Take-Profit** | Unrealized PnL ≥ +80% | Close position immediately |
| **Trailing Stop** | Price dropped ≥15% from peak since entry | Close position |
| **Time Decay** | <24h to settlement AND PnL ≤ -10% | Close position |

### 6.2 Rebalancing

```python
# Only if position is losing (PnL ≤ -15%)
# Find new market with edge ≥ 2× current edge
# Close loser, open new bet with Kelly sizing
if current_edge > 0 and new_edge >= 2 * current_edge and current_pnl <= -0.15:
    close_loser()
    open_new_bet()
```

### 6.3 Portfolio-Level Circuit Breaker

```python
# RiskManager.update_daily_pnl(pnl)
if daily_pnl <= -daily_loss_limit_amount:  # 20% of portfolio
    logger.warning("DAILY STOP-LOSS TRIGGERED!")
    return False  # Halts all new bets
```

---

## 7. Three-Layer AI Optimization Stack

### 7.1 Layer 1: Karpathy Weekly (Slowest, Broadest)

**File:** `asi_engine/karpathy_weekly.py`

- **Schedule:** Weekly (or manual via `python -m asi_engine.karpathy_weekly`)
- **Data:** `UnifiedDatastore.build_brier_dataset()` — real settled markets with actual temperatures (90 days, 15 cities)
- **Method:** Walk-forward splits (no temporal leakage), hypothesis mutation (weights + params + harness variants)
- **Evaluation:** Out-of-sample Sharpe ratio on test windows
- **Output:** `data/karpathy_best.json` + `data/karpathy_results.tsv`
- **Key Discovery:** Asymmetric-payoff fix → `min_entry_price ≈ 0.35`, `inefficiency_min ≈ -0.124`
- **LLM:** Optional (ZAI/GLM via `llm_client`), falls back to deterministic mutation ladder

### 7.2 Layer 2: ASI-Evolve Daily (Medium)

**File:** `asi_engine/asi_evolve.py`

- **Schedule:** Daily
- **Candidates:** 50–200 per run
- **Selection:** UCB1 bandit (exploration/exploitation)
- **Mutation Surface:** Weights + params only (NOT harness code)
- **Feeds:** Best candidate → Layer 3 (SIA) as starting point

### 7.3 Layer 3: SIA Hourly (Fastest, Narrowest)

**File:** `asi_engine/sia_hourly.py`

- **Schedule:** Hourly (via `settlement_loop` → `sia_loop.run_optimization_cycle()`)
- **Two Tracks:**
  1. **Weight Update** (always runs): Gradient-free nudge on `model_weights` dict
  2. **Harness Update** (LLM required): Proposes code patch to `sia_harness.py::predict_yes_probability()`
- **Validation:** AST syntax check (`_validate_harness_patch`) + sandbox smoke test (subprocess eval on OOS window)
- **Persistence:** `data/sia_hourly_best.json` + `data/sia_hourly_results.tsv`
- **Harness Target:** `asi_engine/sia_harness.py` — single function turning per-model forecasts → YES probability

---

## 8. Settlement & PnL

### 8.1 Resolution Source

**Gamma API:** `https://gamma-api.polymarket.com/markets/{condition_id}`

Checks: `closed == true`, `umaResolutionStatus == "resolved"`, valid `outcomePrices`

### 8.2 Payout Calculation

```python
# utils/formulas.py
def settlement_payout(stake, entry_price):
    """Gross payout when a bet wins: stake / entry_price."""
    return stake / entry_price if entry_price > 0 else 0.0

def settlement_pnl(stake, entry_price, entry_fee, won):
    """Realised PnL when Polymarket resolves a bet.

    Fee is charged at TRADE MATCH TIME (entry), NOT at settlement.
    At settlement: outcome share price = $1.00 (won) or $0.00 (lost),
    so p × (1-p) = 0 → settlement fee is mathematically zero.

    When won:
      payout       = stake / entry_price      (= shares × $1.00)
      settlement_fee = 0
      net_pnl      = payout − stake − entry_fee

    When lost:
      net_pnl      = −stake − entry_fee       (stake + fee already paid)

    entry_fee is calculated at bet placement and stored in Bet.entry_fee.
    See polymarket_fee() / polymarket_fee_from_stake() in this module.
    """
    if not won:
        return -(stake + entry_fee)
    payout = settlement_payout(stake, entry_price)
    return payout - stake - entry_fee
```

### 8.3 Accounting (`utils/accounting.py`)

- `credit_sale(session, amount, reason)` — adds to cash, updates Portfolio
- `debit_purchase(session, amount, reason)` — subtracts from cash
- Portfolio `total_value` = cash + unrealized PnL (marked to market)
- `total_realized_pnl` tracks only settled bets

---

## 9. API & Monitoring (FastAPI on :8091)

**File:** `api.py`

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | Bot state, last scan, portfolio, open bets count |
| `GET /api/history` | Settled bets with PnL |
| `GET /api/equity-curve` | Portfolio value over time |
| `GET /api/signals` | Recent analyses with edges |
| `GET /api/asi/weights` | Current model weights + SIA best |
| `GET /api/slippage` | Slippage model stats |
| `GET /api/health-check` | Liveness probe |
| `WS /ws` | Real-time scan updates |

**WebSocket:** Broadcasts `scan_complete` after each cycle.

---

## 10. Key Limits Summary

| Limit | Value | Enforced Where |
|-------|-------|----------------|
| Max single bet | 0.6% of portfolio ($6 on $1000) | `max_bet_pct` in Kelly calc |
| Max total exposure | 25% of portfolio | `RiskManager.check_exposure_cap()` |
| Max bets per city | 4 | `RiskManager.check_city_cap()` |
| Min edge (base) | 5% | `StrategyConfig.min_edge` |
| Effective min edge (at close) | 10% (2× ramp) | `compute_effective_min_edge()` |
| Kelly fraction | 15% (clamped 5–25%) | `StrategyConfig.kelly_fraction` |
| Blend weight | 45% (clamped 35–50%) | `StrategyConfig.blend_weight` |
| Min entry price | 5% (clamped) | `StrategyConfig.min_entry_price` |
| Min YES probability | 15% | `StrategyConfig.min_yes_prob` |
| Daily loss limit | 20% | `RiskManager.update_daily_pnl()` |
| Stop-loss | 20% | `SettlementEngine._check_early_exit()` |
| Take-profit | 80% | `SettlementEngine._check_early_exit()` |
| Trailing stop | 15% | `SettlementEngine._check_early_exit()` |
| Time decay window | 24h before settlement | `RiskConfig.time_decay_hours` |
| Rebalance edge ratio | ≥2× | `SettlementEngine._check_rebalance()` |
| Scan interval | 300s (5 min) | `BotConfig.scan_interval` |
| Midnight fast-scan | 60s for 60 min | `BotConfig.midnight_scan_interval/window` |
| Settlement interval | 120s (2 min) | `BotConfig.settlement_interval` |
| SIA interval | 86400s (24h) | `BotConfig.sia_interval` |
| Open-Meteo throttle | 6s/req (1 req/s) | `OPEN_METEO_MIN_INTERVAL_S` |
| Forecast cache TTL | 30 min success / 5 min fail | `_SUCCESS_TTL_S`, `_FAILURE_TTL_S` |
| 429 global cooldown | 30s | `_GLOBAL_429_COOLDOWN_S` |
| Thread timeouts | 5–10 min | `bot_loop.py` `asyncio.wait_for()` |

---

## 11. File Structure (Key Modules)

```
ASIAbot/
├── main.py                    # Entry point, FastAPI lifespan, bot loops
├── api.py                     # REST + WebSocket endpoints
├── bot_loop.py                # scan_and_bet_loop, settlement_loop
├── config/
│   └── settings.py            # ALL configuration (single source)
├── database/
│   ├── db.py                  # SQLAlchemy session factory
│   ├── models.py              # ORM: WeatherMarket, WeatherForecast, Analysis, Bet, Portfolio, ModelPerformance
│   └── db_cleanup.py          # Archive old forecasts, VACUUM
├── engine/
│   ├── calculator.py          # Calculator, WeatherEngine, CalibrationEngine
│   ├── strategy.py            # RiskManager, SIALoop
│   └── decision.py            # BetDecision gate system
├── executor/
│   ├── bet_placer.py          # BetPlacer (15+ helper methods)
│   └── settler.py             # SettlementEngine (early exit, rebalance)
├── scrapers/
│   ├── polymarket.py          # Gamma API market fetch + parse
│   ├── meteo.py               # MeteoFetcher (Open-Meteo + WeatherAPI)
│   └── async_client.py        # AsyncHttpClient with throttle/semaphore
├── asi_engine/
│   ├── sia_hourly.py          # Layer 3: hourly weight + harness update
│   ├── karpathy_weekly.py     # Layer 1: weekly hypothesis search
│   ├── asi_evolve.py          # Layer 2: daily UCB1 evolution
│   ├── sia_harness.py         # Target of harness patches
│   ├── calibration_engine.py  # Per-model MBE from settled markets
│   └── llm_client.py          # ZAI/GLM chat_json wrapper
├── data_pipeline/
│   └── unified_datastore.py   # Builds Brier dataset for Karpathy
├── utils/
│   ├── probability.py         # estimate_probability, normal_cdf
│   ├── kelly.py               # kelly_bet_amount, dynamic_max_bet_pct
│   ├── slippage.py            # estimate_slippage (orderbook/tiered/flat)
│   ├── formulas.py            # max_bet_cap, portfolio_total_value, settlement_pnl
│   ├── weights_store.py       # Load/save model_weights, strategy_params
│   ├── accounting.py          # credit_sale, debit_purchase
│   ├── price_sanity.py        # is_valid_binary_price
│   └── retry.py               # @retry decorator
├── jobs/
│   └── scheduler.py           # run_cycle, run_fetch_*, run_settle
├── data/
│   ├── bot.db                 # SQLite database
│   ├── strategy_params.json   # Karpathy winners (min_edge, kelly_fraction, blend_weight)
│   ├── model_weights.json     # SIA persisted weights
│   ├── sia_hourly_best.json   # SIA best harness + weights
│   ├── karpathy_best.json     # Karpathy best hypothesis
│   └── asi_calibration.json   # Per-model bias corrections
└── logs/
    ├── bot.log                # Main log
    ├── bot_out.log            # Stdout
    └── bot_err.log            # Stderr
```

---

## 12. Running the Bot

```bash
# Development (paper mode)
cd C:\Users\fdemir\Documents\New project\ASIAbot
python main.py bot

# Or via batch file
run_bot.bat

# API only (no bot loops)
python main.py api
```

**Environment (.env):**
```env
POLY_PRIVATE_KEY=...          # For live trading (DRY_RUN=false)
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...
WEATHERAPI_KEY=...            # Optional backup weather source
ZAI_API_KEY=...               # For SIA/Karpathy LLM features
DRY_RUN=true                  # Enforced paper mode
INITIAL_PORTFOLIO=1000
MAX_BET_PCT=0.006
KELLY_FRACTION=0.15
MIN_ENTRY_PRICE=0.35          # Karpathy-tuned
INEFFICIENCY_MIN=-0.124       # Karpathy-tuned
```

---

## 13. Critical Design Decisions

1. **Single Config Source:** `bot_config` (BotConfig) is the ONLY config. `Config` proxy provides backward compatibility.

2. **No Shared Sessions in Async:** Each async task creates its own `get_session()` — prevents SQLAlchemy deadlocks.

3. **Global 429 Cooldown:** One rate limit cools down ALL cities, not per-city exponential backoff.

4. **Blend Weight Clamp at 0.50:** Pure model (1.0) causes systematic NO bias on low-price markets. Market anchor prevents this.

5. **Min Edge Floor 0.05:** Below 5% edge = negative EV after 5% fee + ~1% slippage + gas.

6. **Kelly Fraction 0.15 (Quarter-Kelly):** Full Kelly too aggressive with <50% win rate. Clamped [0.05, 0.25].

7. **Asymmetric-Payoff Fix:** Karpathy search discovered low-price long-shot bets (6% of trades) wipe out 94% winners. `min_entry_price` and `inefficiency_min` filter these.

8. **Time-to-Close Edge Escalation:** Demand stronger edge near settlement (2× at 0h) because forecast uncertainty drops and market prices converge.

9. **Orderbook-Aware Slippage:** Live depth check via Gamma API, falls back to tiered model.

10. **All Thread Calls Have Timeouts:** `asyncio.wait_for(to_thread(...), timeout=300-600)` prevents infinite hangs.

---

## 14. Known Issues / TODO

- [x] `bet_placer.py` line ~36: `name 'analysis' is not defined` error in exception handler (variable scope bug) — **FIXED**
- [x] `WeatherEngine.warm_start_from_db()` not called on startup (PER-5 fix pending) — **FIXED** (added to main.py lifespan)
- [x] `min_depth_usd` filter disabled (0.0) — orderbook depth check not enforced — **FIXED** (set to 50.0)
- [ ] CalibrationEngine needs 500+ settled bets for stable Platt scaling (currently MBE only)
- [ ] SIA harness patches require LLM (ZAI_API_KEY) — weight-only mode without it
- [ ] Documentation updated to match actual code (uncertainty scaling, high-uncertainty guard, settlement PnL fee, Kelly defaults)

---

*Generated from codebase analysis — ASIAbot v2026.07*