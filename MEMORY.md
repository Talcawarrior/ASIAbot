# ASIAbot Memory Bank
*Last updated: 2025-07-13*

## Project Structure
- **Root**: C:\Users\fdemir\Documents\New project\ASIAbot
- **Bot entry**: main.py (command: `python main.py bot`)
- **API**: api.py (FastAPI on port 8091)
- **Bot loops**: bot_loop.py (scan_and_bet_loop, settlement_loop)
- **Config**: config/settings.py (BotConfig, StrategyConfig)

## Key Config (Current)
```python
# StrategyConfig (data/strategy_params.json)
min_edge: 0.15
kelly_fraction: 0.15
blend_weight: 0.35
model_weights: {
  ecmwf_ifs025: 0.4334,    # 43%
  icon_global: 0.195,       # 20%
  ukmo_seamless: 0.1516,    # 15%
  gem_global: 0.1083,       # 11%
  gfs_seamless: 0.0563,     # 6%
  jma_seamless: 0.0363,     # 4%
  cma_grapes_global: 0.0095,
  meteofrance_seamless: 0.0095
}
```

## Database (data/bot.db)
- **weather_markets**: 144 settled (Jun 28 - Jul 12), 624 open
- **historical_calibrations**: 68,696 rows (8 models × 30 days × 18 cities)
- **analyses**: 504K rows
- **bets**: 894 total (105 won, 71 lost, 703 closed_early)

## Model Names (DB vs Config)
| DB Name | Config Name | Status |
|---------|-------------|--------|
| ecmwf_ifs025 | ecmwf_ifs025 | ✅ |
| icon_global | icon_global | ✅ |
| ukmo_seamless | ukmo_seamless | ✅ |
| gem_global | gem_global | ✅ |
| gfs_seamless | gfs_seamless | ✅ |
| jma_seamless | jma_seamless | ✅ |
| cma_grapes_global | cma_grapes_global | ✅ |
| meteofrance_seamless | meteofrance_seamless | ✅ |

## Karpathy Weekly (Production)
- **File**: asi_engine/karpathy_weekly.py
- **Schedule**: Sunday 03:00 UTC (main.py lifespan)
- **Data**: 130 settled markets + 11K counterfactual + 68K calibrations
- **Best**: Brier 0.185, ROI +587%, Sharpe -0.94
- **Best weights**: ECMWF 43%, ICON 20%, UKMO 15%, GEM 11%

## Backtest Optimization
- **File**: scripts/backtest_optimize_v2.py
- **Best params**: min_edge=0.15, blend=0.35 → Sharpe +0.11, ROI +3.5%
- **Current config**: min_edge=0.15, blend=0.35 ✅

## Polymarket Data
- **Gamma API**: https://gamma-api.polymarket.com/markets (100/page limit)
- **Closed markets**: 144 settled (Jun 28 - Jul 12)
- **Weather markets**: 8 precipitation (all "No"), 0 temperature
- **Local DB**: 144 settled markets (Jun 28 - Jul 12)

## Bot Loops (Running)
- **scan_and_bet_loop**: Every ~60s, fetches markets → weather → analysis → bets
- **settlement_loop**: Every ~60s, checks resolved markets → settles
- **karpathy_weekly_loop**: Sunday 03:00 UTC
- **asi_evolve_daily_loop**: Daily 02:00 UTC
- **sia_hourly**: In settlement loop (weight mutation)

## Key Files (Read Once)
| File | Purpose | Status |
|------|---------|--------|
| main.py | Entry point, lifespan | ✅ Read |
| api.py | FastAPI routes | ✅ Read |
| bot_loop.py | Main loops | ✅ Read |
| engine/calculator.py | Consensus, Kelly, edge | ✅ Read |
| engine/strategy.py | Signal generation | ✅ Read |
| executor/bet_placer.py | Order placement | ✅ Read |
| executor/settler.py | Settlement logic | ✅ Read |
| asi_engine/karpathy_weekly.py | Weekly optimization | ✅ Read |
| asi_engine/sia_hourly.py | Hourly weight mutation | ✅ Read |
| asi_engine/asi_evolve.py | Daily evolution | ✅ Read |
| data_pipeline/unified_datastore.py | Data layer | ✅ Read |
| data_pipeline/polymarket_ingest.py | Gamma API client | ✅ Read |
| config/settings.py | All config | ✅ Read |
| utils/formulas.py | Math formulas | ✅ Read |
| utils/kelly.py | Kelly math | ✅ Read |

## Tests (All Pass)
- 420 unit tests pass
- 10 smoke tests pass
- 5-TEST RULE: ruff, mypy, pytest, next build, smoke tests all pass

## Known Issues
1. `tasks: []` in /api/status - display bug only, loops running
2. `model_weights.json` was stale (uniform) - FIXED to karpathy weights
3. `strategy_params.json` model_weights had wrong names (icon_seamless vs icon_global) - FIXED
4. No temperature markets in June - only 8 precipitation markets

## Commands
```bash
# Run bot
python main.py bot

# Run tests
pytest tests/test_logic_trace.py tests/test_structural_integrity.py tests/test_smoke.py -q

# 5-TEST RULE
ruff check . --fix && mypy . --ignore-missing-imports && pytest -q && npx next build && pytest tests/test_smoke.py -v

# Karpathy manual
python -m asi_engine.karpathy_weekly --rounds 3 --seed 42
```