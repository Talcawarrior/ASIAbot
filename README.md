# ASIAbot — Polymarket Hava Ticaret Botu

**Kendini Geliştiren Yapay Zeka ile Polymarket Hava Tahmin Piyasalarında Otomatik Alım Satım Botu.**

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Özellikler

- **🤖 Tam Otomatik** — Market tarama → hava durumu çekme → analiz → bahis yerleştirme → settlement döngüsü
- **🌤️ 8 Model Ensemble** — GFS, ECMWF, GEM, ICON, JMA, CMA, UKMO, Météo-France — SIA ağırlık optimizasyonu ile
- **🧠 SIA Loop** — Self-Improving Agent, Brier skoruna göre model ağırlıklarını ve strateji parametrelerini otomatik günceller
- **🔬 ASI-Evolve** — Genetik algoritma ile strateji evrimi (virtual backtest + crossover + mutation)
- **📊 Dashboard** — Next.js 16 + shadcn/ui + Recharts ile canlı takip (http://localhost:8091), dark mode desteği
- **⚡ Slippage Modeli** — Tiered sipariş defteri simülasyonu (net edge hesaplama)
- **🛡️ Risk Yönetimi** — Kelly fraction, stop-loss, take-profit, trailing stop, city cap, exposure limit
- **🔍 Karpathy Search** — Grid search ile strateji parametre optimizasyonu (min_edge, kelly_fraction, vs.)
- **🧪 LLM 3-Layer Loop** — Z.AI API ile araştırma, analiz ve karar katmanları
- **📈 Canlı API** — FastAPI + WebSocket ile anlık durum, portföy, PnL, edge dağılımı
- **🧹 Pre-commit Pipeline** — Ruff + Mypy ile otomatik kalite kontrol
- **🌙 Midnight Scan** — Gece yarısı sonrası 60 sn aralıkla 2 gün ileri piyasaları tarar
- **💰 Ladder Betting** — 3 kademeli bahis (50%/30%/20%) — yüksek edge'de kademeli giriş
- **🔐 API Auth** — `X-API-Key` header ile koruma; dev modda serbest
- **📦 DB Archival** — Hot (10g SQLite) → Cold (10-120g Parquet) → Purge (>120g)

---

## Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ASIAbot Core                                 │
├─────────────┬───────────────┬──────────────┬────────────────────────┤
│  Scrapers   │   Weather     │   Engine     │   Executor             │
│  ┌──────┐   │   ┌────────┐  │  ┌─────────┐ │  ┌──────┐  ┌───────┐  │
│  │Poly  │   │   │Open-   │  │  │Analiz   │ │  │Bet   │  │Settle│  │
│  │Market│───┼──▶│Meteo   │──┼─▶│Kalsülasyon│─┼─▶│Placer│─▶│ment  │  │
│  └──────┘   │   │8 Model │  │  │+ Edge   │ │  └──────┘  └───────┘  │
│             │   └────────┘  │  └─────────┘ │                       │
│  ┌──────┐   │              │  ┌─────────┐ │  ┌──────────────────┐ │
│  │Gamma │   │              │  │SIA Loop │ │  │Risk Manager     │ │
│  │ API  │   │              │  │(Ağırlık │ │  │Kelly/Stop/Expo..│ │
│  └──────┘   │              │  │Optim.)  │ │  └──────────────────┘ │
└─────────────┴───────────────┴──┴─────────┴─┴──────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│                       ASI-Evolve                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │Orchestrator  │─▶│Genetik Algo  │─▶│Virtual Backtest + Crossover│ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │Calibration   │  │Data Backfiller│  │Cognition Base (Insights)│  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│                       API & Dashboard                                │
│  FastAPI (port 8091) ←── Next.js 16 Static Export                 │
│  /api/status, /api/markets, /api/bets, /api/signals, /api/history │
│  /api/health-check, /api/asi/weights, /api/asi/evolve             │
│  WebSocket /ws ───→ Canlı güncellemeler                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Veri Akışı

1. **Fetch** — Polymarket gamma-api ile açık hava piyasalarını tara (tarih bazlı sorgular: bugün+2 gün)
2. **Weather** — Open-Meteo API'den 8 farklı modelin tahminlerini çek
3. **Weight** — SIA ağırlıkları ile weighted ensemble hesapla
4. **Calibrate** — Kalibrasyon düzeltmesi uygula (şehir bazlı bias)
5. **Analyze** — Edge = model_prob - market_price; Kelly büyüklük + slippage
6. **Place** — 3 kademeli ladder ile bahis yerleştir (50%/30%/20%)
7. **Settle** — Settlement sonrası PnL güncelle, SIA feedback
8. **Archive** — Hot DB → Cold Parquet → Purge (10g/120g eşikleri)

---

## Hızlı Başlangıç

### Gereksinimler

- Python 3.12+
- Node.js 20+ (dashboard build için)
- Bir Polymarket hesabı ve API anahtarları

### Kurulum

```bash
# Repoyu klonla
git clone https://github.com/Talcawarrior/ASIAbot.git
cd ASIAbot

# Python bağımlılıkları
pip install -r requirements.txt

# .env yapılandırması
cp .env.example .env
# .env dosyasını düzenle (API anahtarları, tercihler)

# Veritabanı
python -c "from database.db import init_db; init_db()"
```

### Dashboard Build

```bash
# Root'tan build et (out/ dizini otomatik oluşturulur)
npm run build
```

> **Not:** `output: "export"` modu `out/` dizinine statik HTML/CSS/JS üretir. Bot `python main.py bot` ile başlatıldığında dashboard otomatik build edilir (src/ out/'tan yeniyse).

### API Güvenliği (Production)

Bot'u internete açmadan önce **mutlaka** `ASIABOT_API_KEY` env değişkenini set edin:

```bash
# Güçlü anahtar üret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# .env dosyasına ekle
echo "ASIABOT_API_KEY=ürettiğin_anahtar" >> .env
```

Set edildiğinde, tüm POST endpoint'leri `X-API-Key` header'ı gerektirir:

```bash
curl -X POST http://localhost:8091/api/reset \
  -H "X-API-Key: ürettiğin_anahtar"
```

> ⚠️ **Uyarı:** `ASIABOT_API_KEY` set edilmezse API açık modda çalışır — tüm POST endpoint'leri (reset, cleanup, start/stop) kimlik doğrulamasız çalışır. **Sadeca localhost için güvenlidir.** `HOST=0.0.0.0` yapmadan önce mutlaka set edin.

### Çalıştırma

```bash
# Bot + API + Dashboard + Background loops (hepsi bir arada)
python main.py bot

# Sadece API + Dashboard (bot loop'ları olmadan)
python main.py run

# Tek seferlik operasyonlar
python main.py fetch    # Marketleri tara
python main.py analyze  # Analiz yap
python main.py bet      # Bahis yerleştir
python main.py settle   # Settlement
python main.py report   # Rapor
```

Bot ayağa kalktığında:
- **API**: http://localhost:8091
- **Dashboard**: http://localhost:8091 (Next.js static export)
- **Swagger**: http://localhost:8091/docs

> **Port Koruması:** Bot başlatılırken port 8091 meşgulse, o portu kullanan süreç otomatik olarak öldürülür.

### Bot'u Persistent (Sürekli) Çalıştırma

`python main.py bot` komutu shell kapandığında ölür. Bot'u sürekli çalıştırmak için 3 seçenek:

#### Seçenek 1: nohup (en basit, Linux/Mac)
```bash
nohup python main.py bot > bot.log 2>&1 &
echo $!  # PID'yi kaydet
# Durdurmak için: kill <PID>
# Logları izlemek için: tail -f bot.log
```

#### Seçenek 2: tmux (interactive, önerilen)
```bash
tmux new -s asiabot
python main.py bot
# Ctrl+B, sonra D ile detach
# Tekrar bağlan: tmux attach -t asiabot
# Durdur: tmux kill-session -t asiabot
```

#### Seçenek 3: systemd (production, auto-restart)
```bash
# /etc/systemd/system/asiabot.service dosyası oluştur:
sudo tee /etc/systemd/system/asiabot.service << 'EOF'
[Unit]
Description=ASIAbot - Polymarket Weather Trading Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/ASIAbot
EnvironmentFile=/path/to/ASIAbot/.env
ExecStart=/path/to/python main.py bot
Restart=always
RestartSec=10
StandardOutput=append:/var/log/asiabot.log
StandardError=append:/var/log/asiabot.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable asiabot
sudo systemctl start asiabot

# Durum: sudo systemctl status asiabot
# Loglar: sudo journalctl -u asiabot -f
# Durdur: sudo systemctl stop asiabot
```

---

## API Referansı

### Durum ve Portföy

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/status` | Bot durumu, portföy değeri, PnL, açık bahisler |
| `GET /api/health-check` | Kapsamlı sağlık kontrolü (edge dağılımı, red flags, 7 günlük PnL) |

### Piyasalar ve Bahisler

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/markets` | Tüm hava piyasaları + tahminler |
| `GET /api/bets` | Bahis geçmişi (status, limit, offset filtresi) |
| `GET /api/signals` | Açık pozisyonlar + canlı edge takibi |
| `GET /api/history` | Kapanmış bahislerin W/L/ROI geçmişi (exit_price dahil) |
| `GET /api/equity-curve` | Günlük PnL serisi (portföy değeri zaman grafiği) |
| `GET /api/slippage` | Slippage tahmin kayıtları (model doğrulama) |
| `GET /api/asi/trades` | On-chain Polymarket trade verisi |
| `GET /api/asi/orderbook` | ResolvedMarkets'ten CLOB orderbook derinliği |

### ASI-Evolve

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/asi/weights` | Güncel model ağırlıkları |
| `GET /api/asi/cognition` | Cognition Base içgörüleri |
| `GET /api/asi/calibration` | Şehir bazlı bias kalibrasyon haritası |
| `POST /api/asi/evolve` 🔒 | 5 turlu evrim pipeline'ı başlat |
| `POST /api/asi/backfill` 🔒 | Tarihsel veri backfill (Open-Meteo) |
| `POST /api/asi/calibration/recalculate` 🔒 | Kalibrasyon bias'larını yeniden hesapla |

### Kontrol

| Endpoint | Açıklama |
|----------|----------|
| `POST /api/cleanup` 🔒 | Eski bet'leri iptal et + stake iadesi |
| `POST /api/start` 🔒 | Bot döngülerini başlat |
| `POST /api/stop` 🔒 | Bot döngülerini durdur |
| `POST /api/reset` 🔒 | Bot'u sıfırla (tüm bet'leri iptal et, portföyü resetle) |
| `WS /ws` | WebSocket canlı güncellemeler |

> 🔒 = **Korunan endpoint**. `ASIABOT_API_KEY` env değişkeni set edildiğinde, bu endpoint'ler `X-API-Key` header'ı gerektirir. Set edilmezse API açık modda çalışır (sadece localhost için güvenli).

---

## Konfigürasyon

### `.env` Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DRY_RUN` | `true` | Gerçek emir göndermeden simülasyon |
| `INITIAL_PORTFOLIO` | `1000.0` | Başlangıç portföy değeri ($) |
| `SCAN_INTERVAL` | `300` | Market tarama aralığı (saniye) |
| `SETTLEMENT_INTERVAL` | `120` | Settlement kontrol aralığı (saniye) |
| `SIA_INTERVAL` | `86400` | SIA optimizasyon aralığı (saniye) |
| `MAX_EXPOSURE_PCT` | `0.25` | Maksimum exposure oranı |
| `MAX_BET_PCT` | `0.03` | Maksimum bet büyüklüğü (portföy %3'ü) |
| `MAX_BET_AMOUNT` | `3.0` | Maksimum tek bahis tutarı ($) |
| `DAILY_LOSS_LIMIT` | `0.05` | Günlük zarar limiti (portföy %5'i) |
| `KELLY_FRACTION` | `0.15` | Fractional Kelly katsayısı |
| `CITY_CAP` | `4` | Şehir başına maksimum pozisyon |
| `HOST` | `127.0.0.1` | Sunucu adresi |
| `PORT` | `8091` | API portu |
| `FEE_DRAG` | `0.05` | Polymarket Weather taker fee (%5) |
| `ASIABOT_API_KEY` | — | API koruması için anahtar (yoksa açık mod) |

> **Not:** `MAX_BET_PCT` ve `MAX_BET_AMOUNT` .env.example ile senkron tutulur. `FEE_DRAG` gerçek Polymarket Weather kategori fee oranı olan %5'e ayarlı (eski sürümlerde yanlış %2 idi).

### Risk Parametreleri

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `take_profit_pct` | `1.0` | Take-profit eşiği (%100 kâr) |
| `stop_loss_pct` | `0.20` | Stop-loss eşiği (%20 zarar — hızlı kayıp kesme) |
| `trailing_stop_pct` | `0.15` | Trailing stop eşiği (%15 gerileme) |
| `MIN_HOLD_MINUTES` | `3` | Minimum bekleme süresi (dakika) |

### LLM Yapılandırması

```env
ZAI_API_KEY=anahtar                          # Z.AI API anahtarı
ZAI_BASE_URL=https://api.z.ai/api/paas/v4/   # API base URL
LLM_MODEL=glm-4.5-flash                       # Model adı
```

### Strateji Parametreleri

Parametreler `data/strategy_params.json` üzerinden yönetilir — Karpathy Search veya SIA Loop tarafından otomatik güncellenir:

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `min_edge` | 5% | Minimum edge eşiği |
| `kelly_fraction` | 15% | Fractional Kelly |
| `min_entry_price` | 0.35 | Minimum giriş fiyatı |
| `inefficiency_min` | -0.124 | Minimum verimsizlik eşiği |

### Midnight Scan

Gece yarısı sonrası bot, 2 gün ileri tarihli piyasaları erken yakalamak için özel tarama moduna geçer:

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `midnight_scan_interval` | `60` | Tarama aralığı (saniye) |
| `midnight_scan_window` | `60` | Tarama süresi (dakika) |

---

## Modeller

SIA Loop tarafından optimize edilen 8 hava modeli:

| Model | Varsayılan Ağırlık | Kaynak |
|-------|-------------------|--------|
| GFS Seamless | %35 | NOAA |
| ECMWF IFS 0.25 | %35 | ECMWF |
| GEM Global | %5 | Environment Canada |
| ICON Global | %5 | DWD (Almanya) |
| JMA Seamless | %5 | Japan Meteorological Agency |
| CMA Grapes Global | %5 | China Meteorological Administration |
| UKMO Seamless | %4 | UK Met Office |
| Météo-France Seamless | %3 | Météo-France |

---

## CLI Komutları

```bash
# Ana komutlar
python main.py bot          # Bot + API + Dashboard + background loops
python main.py run          # Sadece API + Dashboard

# Tek seferlik işlemler
python main.py fetch        # Marketleri tara
python main.py weather      # Hava durumunu çek
python main.py analyze      # Analiz yap
python main.py bet          # Bahis yerleştir
python main.py settle       # Settlement
python main.py report       # Rapor
```

---

## Geliştirme

### Kalite Araçları

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy .

# Tüm testler
PYTHONPATH=. pytest

# Coverage
coverage run -m pytest
coverage report

# Pre-commit (otomatik çalışır)
pre-commit run --all-files

# Full pipeline
ruff check . && mypy . && pytest
```

### Test Yapısı

```
tests/
├── test_accounting.py               # Portföy muhasebe testleri
├── test_active_risk_management.py    # Risk yönetimi testleri
├── test_api_bets.py                 # API bahis endpoint testleri
├── test_api_integration.py          # API entegrasyon testleri
├── test_asi_evolve.py               # ASI-Evolve testleri
├── test_calculator.py                # Hava durumu hesaplama
├── test_calculator_min_edge.py       # Edge eşiği testleri
├── test_calculator_real.py           # Gerçek veri ile hesap
├── test_config_consistency.py        # Config tutarlılık
├── test_faz2_e2e_mock.py .. 6.py     # End-to-end mock testleri
├── test_karpathy_weekly.py           # Karpathy search testi
├── test_kelly_wrapper_regression.py  # Kelly wrapper regresyon
├── test_live_data_smoke.py           # Canlı veri smoke testi
├── test_llm_loop_orchestrator.py     # LLM loop testleri
├── test_meteo.py                     # Open-Meteo testleri
├── test_meteo_cache_ttl.py           # Cache TTL testleri
├── test_polymarket_mock.py           # Polymarket mock testleri
├── test_polymarket_real.py           # Polymarket gerçek testleri
├── test_researcher_agent_honesty.py  # Araştırma agent dürüstlük
├── test_sia_hourly.py                # SIA Loop testleri
├── test_slippage.py                  # Slippage modeli
└── test_weights_store.py             # Ağırlık depolama
```

---

## Proje Yapısı

```
ASIAbot/
├── asi_engine/          # ASI-Evolve: calibration, cognition, evolving
├── config/              # Settings, logging
├── data/                # Runtime veri (weights, params, backtest)
├── data_pipeline/       # PolyMarket veri çekme + işleme
├── database/            # SQLAlchemy ORM (Bet, Portfolio, Analysis..)
├── engine/              # Core: calculator, strategy, risk manager
├── executor/            # BetPlacer, Settlement
├── jobs/                # Zamanlanmış görevler (scheduler)
├── scrapers/            # Polymarket, Open-Meteo API clients
├── scripts/             # Diagnostic/utility script'ler
├── src/                 # Next.js dashboard (app/, lib/, components/)
├── tests/               # 308 test
├── utils/               # Kelly, slippage, probability, accounting, formulas
├── main.py              # Bot + API + CLI giriş noktası
├── api.py               # FastAPI endpoint'leri
├── bot_loop.py          # Bot döngüsü + midnight scan
├── .pre-commit-config.yaml  # Pre-commit hooks
├── mypy.ini             # Mypy yapılandırması
└── pyrightconfig.json   # Pyright yapılandırması
```

---

## Lisans

MIT
