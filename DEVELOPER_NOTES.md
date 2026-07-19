# GeliÅŸtirici NotlarÄ± â€” asiabot Bot

## ZORUNLU: Her Kod DeÄŸiÅŸikliÄŸi SonrasÄ±

```bash
python quick_check.py          # 7 test, ~78 saniye
python quick_check.py --fast   # sadece lint + import, ~15 saniye
```

Bu testleri **her commit Ã¶ncesi** ve **bot restart Ã¶ncesi** Ã§alÄ±ÅŸtÄ±r.
Test geÃ§mezse commit yapma, push etme.

---

## Test KatmanlarÄ±

| # | AraÃ§ | Ne yapar | Dosya |
|---|------|----------|-------|
| 1 | **RUFF** | Undefined names (F821), bare except (E722), unused imports (F401) | quick_check.py |
| 2 | **PYLINT** | Code quality: broad except, reimport, fstring logging | quick_check.py |
| 3 | **MYPY** | Type annotations, Optional hatalarÄ± | quick_check.py |
| 4 | **CRITICAL** | 26 regression test: timezone, API, scraper, DB, backup, take profit | test_critical_bugs.py |
| 5 | **UNIT+RISK** | 104 test: formÃ¼l, kelly, risk manager, take profit | 3 test dosyasÄ± |
| 6 | **REGRESSION** | 27 test: bilinen bug'larÄ±n tekrarlamamasÄ± | test_regression.py |
| 7 | **IMPORT** | TÃ¼m kritik modÃ¼ller import edilebilir | quick_check.py |

---

## Bilinen Kritik Hatalar ve Ã‡Ã¶zÃ¼mleri

### B3 â€” max_bet_pct 10x Fark
- `config/settings.py`: `max_bet_pct = 0.003` (%0.3)
- `utils/kelly.py`: `max_bet_pct = 0.03` (%3)
- **Ã‡Ã¶zÃ¼m**: `kelly.py` artÄ±k `bot_config.strategy.max_bet_pct` okuyor

### B4 â€” Fee Rate TutarsÄ±zlÄ±ÄŸÄ±
- `config/settings.py`: `fee_drag = 0.02` (Ã¶lÃ¼ kod)
- `utils/slippage.py`: `FEE_PCT = 0.05` (hardcoded)
- `strategy.py`: `current_fee_rate` (dinamik)
- **Ã‡Ã¶zÃ¼m**: strategy.py artÄ±k `current_fee_rate` kullanÄ±yor. `slippage.py` de gÃ¼ncellendi.

### B5 â€” min_edge Ã‡ifte Kontrol
- `calculator.py`: `effective_min_edge` (dinamik, time-to-close)
- `strategy.py`: dÃ¼z `min_edge` (sabit %5)
- **Ã‡Ã¶zÃ¼m**: strategy.py'deki min_edge check kaldÄ±rÄ±ldÄ±, calculator'a bÄ±rakÄ±ldÄ±.

### Timezone Crash (bot_loop.py)
- `fast_mode_until` timezone-aware, `now` naive â†’ crash
- **Ã‡Ã¶zÃ¼m**: `fast_mode_until` artÄ±k `.replace(tzinfo=None)` yapÄ±yor

### Gamma API Format DeÄŸiÅŸikliÄŸi
- Polymarket `tokens[]` dÃ¶ndÃ¼rmÃ¼yor artÄ±k
- **Ã‡Ã¶zÃ¼m**: scraper `outcomePrices` fallback ekledi, `bestBid=0` / `bestAsk=1` atlÄ±yor

### Take Profit Format String
- `{pct:.1%}` 100 ile Ã§arpÄ±yordu (double multiply)
- **Ã‡Ã¶zÃ¼m**: ratio kullanÄ±mÄ±, format `{pct:.1%}` artÄ±k ratio formatlÄ±yor

---

## DB Koruma KurallarÄ±

1. **HiÃ§bir test production DB'ye dokunmaz** â€” `conftest.py` temp DB'ye yÃ¶nlendirir
2. **Her test Ã¶ncesi backup** â€” `conftest.py` `_pre_test_backup()`
3. **Reset Ã¶ncesi backup** â€” `api.py` ve `main.py` reset'ten Ã¶nce backup alÄ±r
4. **Bot startup backup** â€” Her restart'ta `db_backup.py` Ã§alÄ±ÅŸÄ±r
5. **Backup limiti**: MAX_BACKUPS = 10, eski olanlar otomatik temizlenir

```bash
python db_backup.py           # Manuel backup
python db_backup.py --list    # Backup'larÄ± listele
python db_backup.py --restore # Son backup'Ä± geri yÃ¼kle
```

---

## Bot BaÅŸlatma

```bash
python main.py bot             # Botu baÅŸlat
python main.py reset           # Botu sÄ±fÄ±rla (backup alÄ±r)
```

Port: 8091. API key: `.env` dosyasÄ±nda `asiabot_API_KEY`.

### Bot Durumu Kontrol

```bash
# API
curl http://127.0.0.1:8091/api/status

# Log
Get-Content logs\bot.log -Tail 10
```

---

## Branch KullanÄ±mÄ±

| Branch | AmaÃ§ |
|--------|------|
| `restore/05-clean-state` | Ana iÅŸ akÄ±ÅŸÄ± (production) |
| `ponytail-audit` | Ponytail audit + CI testleri |
| `feature/partial-tp` | Partial take-profit Ã¶zelliÄŸi |

### Push KuralÄ±
1. `quick_check.py` 7/7 geÃ§meden push ETME
2. DB'ye dokunmadan push ETME
3. Yeni branch oluÅŸtur, `restore/05-clean-state`'e dokunma

---

## Dosya YapÄ±sÄ±

```
asiabot/
â”œâ”€â”€ bot_loop.py           # Scan + settlement loop
â”œâ”€â”€ main.py               # Bot giriÅŸ noktasÄ±
â”œâ”€â”€ api.py                # FastAPI endpoints
â”œâ”€â”€ quick_check.py        # CI test suite (7 test)
â”œâ”€â”€ db_backup.py          # Backup utility
â”œâ”€â”€ config/settings.py    # Bot config (bot_config singleton)
â”œâ”€â”€ engine/
â”‚   â”œâ”€â”€ strategy.py       # RiskManager + exit checks
â”‚   â”œâ”€â”€ calculator.py     # Probability + edge hesaplama
â”‚   â””â”€â”€ market_parser.py  # Polymarket parser
â”œâ”€â”€ executor/
â”‚   â”œâ”€â”€ bet_placer.py     # Bahis aÃ§ma
â”‚   â””â”€â”€ settler.py        # Bahis kapatma/settlement
â”œâ”€â”€ jobs/
â”‚   â””â”€â”€ scheduler.py      # run_cycle, risk_management
â”œâ”€â”€ scrapers/
â”‚   â”œâ”€â”€ polymarket.py     # Gamma API scraper
â”‚   â””â”€â”€ meteo.py          # Open-Meteo weather fetch
â”œâ”€â”€ utils/
â”‚   â”œâ”€â”€ formulas.py       # pnl_ratio, roi_pct, polymarket_fee
â”‚   â”œâ”€â”€ kelly.py          # Kelly criterion
â”‚   â””â”€â”€ slippage.py       # Slippage + fee hesaplama
â”œâ”€â”€ database/
â”‚   â”œâ”€â”€ db.py             # SQLAlchemy engine + session
â”‚   â”œâ”€â”€ models.py         # Bet, WeatherMarket, Portfolio, Analysis
â”‚   â””â”€â”€ db_cleanup.py     # Parquet archiving
â””â”€â”€ tests/
    â”œâ”€â”€ conftest.py       # DB koruma + backup
    â”œâ”€â”€ test_critical_bugs.py  # 26 kritik regression test
    â”œâ”€â”€ test_take_profit_comprehensive.py  # 23 exit test
    â”œâ”€â”€ test_active_risk_management.py     # 42 risk test
    â”œâ”€â”€ test_units.py     # 104 unit test
    â””â”€â”€ test_regression.py # 27 regression test
```


