# ASIAbot — Agent Instructions

## Entrypoints

- `main.py` — CLI entrypoint. Commands: `bot|run|reset|fetch|parse|weather|analyze|bet|settle|report`
- `python main.py bot` — starts FastAPI + background loops (scan-and-bet + settlement)
- `python main.py run` — API-only (no background loops)
- `api.py` — FastAPI app, routes, BotState, WebSocket. Port 8091

## Quick Verification

Before commit: `python quick_check.py` (7 checks, ~78s) or `--fast` (lint+import, ~15s).
CI runs on push to `main`/`dev` and PR to `main`.

## Quality Gates

`pre-commit run --all-files` runs: ruff check + ruff-format + mypy.
CI pipeline: ruff check → mypy (ignores errors, `|| true`) → pytest units → regression → property → golden → integration → all-tests + coverage.

## Testing

`pytest asyncio_mode = auto` — async tests work without special markers.
`ruff line-length = 120`. `mypy` has many `ignore_errors = True` entries (asi_engine, scrapers, database/models, utils/bet_placer — don't fight mypy there).
Test DB is always in-memory or temp file — `conftest.py` handles isolation. Never read/write `data/bot.db` in tests.

Key test files:
- `test_critical_bugs.py` — 26 regression tests for known bugs (timezone, gamma API, fee rate)
- `test_units.py` — 104 formula/unit tests
- `test_regression.py` — 27 regression tests
- `test_mutation.py` — verifies tests catch real bugs (calculator probability, kelly, formulas)

## Key Env (`.env`)

```
DRY_RUN=true          # paper trading
asiabot_API_KEY=...   # protects POST endpoints
ZAI_API_KEY=...       # LLM (ZhipuAI/GLM)
RESOLVEDMARKETS_API_KEY=...
POLY_PRIVATE_KEY=...  # only needed when DRY_RUN=false
```

## Architecture

```
scrapers/polymarket.py → engine/calculator.py → engine/strategy.py → executor/bet_placer.py
                                                      ↓
                                              executor/settler.py
                                                      ↓
                                              asi_engine/ (self-evolve, calibration, backtest)
```

`engine/calculator.py` — probability from ensemble weather models (Open-Meteo, 8 models with weights).
`engine/strategy.py` — RiskManager (exposure/city/daily-loss caps) + BettingEngine (Kelly, slippage).
`executor/settler.py` — settlement PnL calculation.
`asi_engine/` — self-evolving weights, backtest simulator, calibration, LLM orchestration.

## Known Gotchas

- `max_bet_pct` used to be 10x off in `utils/kelly.py` vs `config/settings.py` — kelly.py now reads `bot_config.strategy.max_bet_pct`
- `min_edge` checked in both `calculator.py` (dynamic, time-to-close aware) and `strategy.py` (static 5%) — strategy check was removed, calculator owns it
- Gamma API changed `tokens[]` format — scraper falls back to `outcomePrices`, skips `bestBid=0`/`bestAsk=1`
- Take profit format `{pct:.1%}` double-multiplied — now uses ratio directly
- `fast_mode_until` in bot_loop.py must be timezone-naive (`.replace(tzinfo=None)`) to match `now`
- mypy section `[mypy-database.models]` has `ignore_errors = True` for SQLAlchemy ORM confusion

## DB Safety

`conftest.py` creates a temp DB per test. Backup before reset: `python db_backup.py`.
Reset flow: archive bets/portfolio to parquet → cancel bets → clear analyses → restore cash.
MAX_BACKUPS = 10; `data/bot.db` is never touched by tests.

## VERI KORUMA KURALLARI

1. **VERI ASLA SILINMEZ, BOZULMAZ, OVERWRITE EDILMEZ** — forecast, metar, price, calibration verisi dahil tum veri kaynaklari KALICIDIR. Yeni veri SADECE INSERT ile eklenir. Eski veri query ile okunur ama ASLA guncellenmez veya silinmez.
2. **Veri kaynagi kontrol zorunlulugu** — "veri yok" denmeden ÖNCE su konumlar kontrol edilir:
   - `C:\Users\fdemir\Documents\New project\ASIAbot\data\*.db` (ana proje)
   - `C:\Users\fdemir\Documents\New project\junbo\data\*.db` (junbo)
   - `C:\Users\fdemir\Documents\New project\junbo\data\backups\` (junbo backuplari)
   - `C:\Users\fdemir\Documents\New project\Heat\` (heat projesi)
   - `D:\ASIA data\` (asia verileri: junbo_bot.db, bot_backup.db, bot_test.db)
   - `D:\JUNBO data\backups\` (junbo dis kaynak)
   - `D:\HEAT data\` (heat verileri: gfs_archive, weather_data, era5)
   - Bot backup'lari (her 6 saatte 1 kayit: `bot_YYYYMMDD_HHMMSS.db`)
3. **Sehir adi vs ICAO kodu karismasi** — `weather_markets.city` = sehir adi (Paris), `weather_markets.city_code` = ICAO (LFPG), `weather_forecasts.city` = ICAO (LFPG). Veri tasirken veya restore ederken bu farklara DIKKAT edilmeli.

## CodeGraph

CodeGraph MCP + autoSync is configured (4s debounce after edits). After every code change, run:
- `codegraph sync` to force immediate graph update
- `codegraph status` to verify index is current

Use `codegraph_explore`, `codegraph_search`, `codegraph_dependencies` for symbol-aware context instead of grep/glob. The graph auto-syncs on file changes but may lag briefly during rapid edits.

## Branching

Main working branch: `restore/05-clean-state`. Push only after `quick_check.py` passes.
