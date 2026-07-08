# ASIAbot — Polymarket Hava Ticaret Botu

**Kendini Geliştiren Yapay Zeka ile Polymarket Hava Tahmin Piyasalarında Otomatik Alım Satım Botu.**

![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-330%20passed-brightgreen)

---

## Özellikler

- **🤖 Tam Otomatik** — Market tarama → hava durumu çekme → analiz → bahis yerleştirme → settlement döngüsü
- **🌤️ 8 Model Ensemble** — GFS, ECMWF, GEM, ICON, JMA, CMA, UKMO, Météo-France — SIA ağırlık optimizasyonu ile (tek Open-Meteo çağrısı, 8 model)
- **🧠 SIA Loop** — Self-Improving Agent, saatlik Brier skoruna + financial feedback'e (Win Rate, ROI) göre model ağırlıklarını ve strateji parametrelerini otomatik günceller (✅ aktif)
- **🌡️ Continuous Calibration** — Her SIA döngüsünde şehir bazlı sıcaklık bias düzeltmesi (60g rolling window, recency weighting, shrinkage)
- **🔬 ASI-Evolve** — Genetik algoritma ile strateji evrimi (UCB1 selection + crossover + mutation ladder)
- **📊 Dashboard** — Next.js 16 + shadcn/ui + Recharts ile canlı takip (http://localhost:8091), dark mode desteği
- **⚡ Slippage Modeli** — 3 model (flat / tiered / orderbook) — VWAP walk + gerçek ResolvedMarkets API
- **🛡️ Risk Yönetimi** — 12 gate (max_entry_price dahil) + 3 cap + 7 early-exit + daily circuit breaker + tier-based priority scoring
- **💰 EV-Proportional Sizing** — Dinamik max_bet_pct (edge band'ine göre: %2/%3/%5) + Kelly fraction + edge-band ladder
- **📈 Ladder Betting** — 3 kademeli bahis; yüksek edge → L1 %70 (agresif), düşük edge → L1 %40
- **🔄 Pyramiding** — Yüksek edge'de L2/L3 fiyat YÜKSELDİĞİNDE dolar (kazanana ekle), düşük edge'de averaging down
- **🔍 Karpathy Search** — Genetic algoritma + mutation ladder ile strateji parametre optimizasyonu (walk-forward OOS doğrulama, temporal leakage yok). Manuel: `python main.py llm karpathy` (⚠️ hazır — trade verisi birikince hipotez kabul eder)
- **🧪 LLM 3-Layer Loop** — Z.AI API ile araştırma, analiz ve karar katmanları (opsiyonel, fallback mutation ladder)
- **📈 Canlı API** — FastAPI + WebSocket (scan_complete broadcast) + 10s/60s polling fallback
- **🌙 Midnight Scan** — Gece yarısı sonrası 60 sn aralıkla 2 gün ileri piyasaları tarar
- **🔐 Duplicate Prevention** — `no_existing_bet` gate + `REOPEN_COOLDOWN_HOURS` (TP/SL sonrası 24h re-entry engeli)
- **📦 DB Archival** — Hot (10g SQLite) → Cold (10-120g Parquet) → Purge (>120g)
- **⚡ Performance** — Paralel tarama, warm-start cache, 5-gün forecast, 20-paralel weather fetch

---

## Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ASIAbot Core                                 │
├─────────────┬───────────────┬──────────────┬────────────────────────┤
│  Scrapers   │   Weather     │   Engine     │   Executor             │
│  ┌──────┐   │   ┌────────┐  │  ┌─────────┐ │  ┌──────┐  ┌───────┐  │
│  │Poly  │   │   │Open-   │  │  │Analiz   │ │  │Bet   │  │Settle│  │
│  │Market│───┼──▶│Meteo   │──┼─▶│+ Edge   │─┼─▶│Placer│─▶│ment  │  │
│  └──────┘   │   │8 Model │  │  │+ Kelly  │ │  └──────┘  └───────┘  │
│  ┌──────┐   │   └────────┘  │  └─────────┘ │                       │
│  │Async │   │              │  ┌─────────┐ │  ┌──────────────────┐ │
│  │Cache │   │              │  │SIA Loop │ │  │Risk Manager     │ │
│  │5dkTTL│   │              │  │(Ağırlık │ │  │12 gate + 3 cap   │ │
│  └──────┘   │              │  │Optim.)  │ │  │7 early-exit      │ │
└─────────────┴───────────────┴──┴─────────┴─┴──────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│                       ASI-Evolve                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │Orchestrator  │─▶│UCB1 + Crossov│─▶│Walk-Forward Backtest OOS │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │Calibration   │  │Data Backfiller│  │Cognition Base (FAISS)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│                       API & Dashboard                                │
│  FastAPI (port 8091) ←── Next.js 16 Static Export                 │
│  /api/status, /api/markets, /api/bets, /api/signals, /api/history │
│  /api/health-check, /api/asi/weights, /api/asi/evolve             │
│  WebSocket /ws ───→ scan_complete broadcast + 10s/60s polling     │
└─────────────────────────────────────────────────────────────────────┘
```

### Veri Akışı

1. **Fetch** — Polymarket gamma-api ile açık hava piyasalarını tara (tarih bazlı sorgular: bugün+2 gün)
2. **Weather** — Open-Meteo API'den 8 modelin tahminlerini çek (tek çağrı, 5 gün)
3. **Weight** — SIA ağırlıkları ile weighted ensemble hesapla
4. **Calibrate** — Continuous calibration düzeltmesi uygula (şehir bazlı bias; 60g rolling window + recency weight)
5. **Analyze** — Edge = model_prob - market_price; net edge = raw - slippage - fee - gas
6. **Size** — Dinamik Kelly: `kelly_bet_amount(edge=...)` → yüksek edge → yüksek bet
7. **Place** — 3 kademeli ladder; yüksek edge → L1 %70, düşük edge → L1 %40
8. **Settle** — Settlement sonrası PnL güncelle, SIA feedback
9. **Archive** — Hot DB → Cold Parquet → Purge (10g/120g eşikleri)

---

## EV-Proportional Bet Sizing (YENİ)

Bot artık **EV'ye orantılı** bet sizing yapıyor — yüksek olasılıklı (yüksek edge) bahislere yüksek bet, düşük EV'ye düşük bet girer.

### Dinamik max_bet_pct (Edge Band'i)

| Edge | max_bet_pct | Kelly Fraction | Ladder Split (L1/L2/L3) |
|------|-------------|----------------|--------------------------|
| ≥ %20 | %5 | 0.25 (quarter Kelly) | 70% / 20% / 10% (pyramiding) |
| %15-%20 | %3 | 0.15 (sub-quarter) | 50% / 30% / 20% (averaging) |
| %10-%15 | %2 | 0.10 | 40% / 35% / 25% (conservative) |
| < %20 | — | — | **min_edge=%20** — bet açılmaz |

### Örnek Hesaplama ($1000 portföy, price=0.50)

| Edge | max_bet_pct | Bet Amount |
|------|-------------|------------|
| %20 | %5 | **$50.00** |
| %15 | %3 | **$30.00** |
| %10 | %2 | **$10.00** |
| <%20 | — | **Açılmaz** (min_edge filtresi) |

### Pyramiding vs Averaging Down

- **Yüksek edge (≥%20):** L2/L3 fiyat **YÜKSELDİĞİNDE** dolar (kazanan pozisyona ekle, tezi doğrula)
- **Düşük edge (<%20):** L2/L3 fiyat **DÜŞTÜĞÜNDE** dolar (maliyet düşür, klasik averaging)

### Min-Bet Floor (Over-Betting Önleme)

Kelly `< min_bet/2` ise bet **açılmaz** (return 0). Eski kod Kelly $0.10 önerse bile $1.0'e yapışıyordu.

---

## Bileşenler

ASIAbot 3 katmanlı otonom optimizasyon sistemine sahiptir:

### 0. Continuous Calibration (Her SIA döngüsünde)

**Dosya:** `asi_engine/calibration_engine.py`

**Ne iş yapar:** Her saatlik SIA döngüsünün **en başında** çalışır. Her şehir ve model için sistematik sıcaklık bias'ını (ör. "GFS İstanbul'da 1.5°C fazla tahmin ediyor") hesaplar ve ham tahmine otomatik düzeltme uygular.

**Yenilikler (2026-07-07):**
- **Rolling window:** Son 60 gün — eski model versiyonlarının bias'ı kullanılmaz
- **Recency weighting:** 14 gün yarı ömürlü üstel ağırlık — dünkü bias, 55 gün öncekinden daha önemli
- **Shrinkage:** Az verili kombinasyonlarda bias 0'a çekilir ("emin değilsen düzeltme yapma")
- **Boş veri koruması:** Son 60 günde hiç veri yoksa eski kalibrasyon haritası korunur

**Çalışma sıklığı:** Her SIA döngüsünde otomatik (eskiden sadece manuel API çağrısı ile)

### 1. ISA / SIA Loop (Self-Improving Agent) — Saatlik

**Dosya:** `asi_engine/sia_hourly.py`

**Ne iş yapar:** Her saat başı çalışır. 8 hava modelinin ağırlıklarını Brier skoruna göre küçük adımlarla optimize eder.

**İki güncelleme kanalı:**
- **Weight update:** Model ağırlıklarını Brier skoruna göre %0.1-1 arası nudge eder (LLM olmadan da çalışır)
- **Harness update:** (opsiyonel, LLM gerekli) `sia_harness.py` koduna yama önerir — syntax + smoke test geçerse kabul edilir

**Çalışma sıklığı:** Her saat (bot loop içinde otomatik)
**Bağımlılık:** LLM opsiyonel (yoksa sadece weight update çalışır)
**Çıktı:** `data/sia_hourly_best.json`, `data/sia_hourly_results.tsv`

**Son çalışma:** `SIA Loop tamamlandi. Win Rate=50.35%, ROI=10.50%` (22:31, 2026-07-06)

---

### 2. ASI-Evolve — Günlük

**Dosya:** `asi_engine/asi_evolve.py`

**Ne iş yapar:** Genetik algoritma (UCB1 selection + crossover + mutation ladder) ile strateji evrimi yapar. 50-200 aday hipotez üretir, walk-forward backtest ile OOS doğrular, en iyiyi seçer.

**Parametreler:**
- Model ağırlıkları (8 model × weight)
- `min_edge` (edge eşiği)
- `kelly_fraction` (Kelly çarpanı)

**Çalışma sıklığı:** Günde 1 kez (arka plan loop'u)
**Bağımlılık:** LLM opsiyonel (yoksa mutation ladder fallback)
**Çıktı:** `data/asi_evolve_best.json`, `data/asi_evolve_results.tsv`

---

### 3. Karpathy Search — Haftalık

**Dosya:** `asi_engine/karpathy_weekly.py`

**Ne iş yapar:** Genetic algoritma + mutation ladder ile strateji parametrelerini geniş bir uzayda tarar. Walk-forward OOS doğrulama ile temporal leakage önler.

**Taranan parametreler:**
- `min_edge` (edge eşiği)
- `kelly_fraction` (Kelly çarpanı)
- `min_entry_price` (minimum giriş fiyatı)
- `inefficiency_min` (minimum verimsizlik)

**Çalışma sıklığı:** Manuel çalıştırma (otomatik cron/scheduler yok)
**Manuel çalıştırma:** `python main.py llm karpathy`
**Bağımlılık:** LLM opsiyonel (yoksa mutation ladder fallback)
**Çıktı:** `data/strategy_params.json`, `data/karpathy_results.tsv`

---

### Katman Hiyerarşisi

```
Karpathy (haftalık, 50-200 aday, geniş tarama)
    ↓ en iyi hipotez
ASI-Evolve (günlük, 50-200 aday, UCB1)
    ↓ en iyi hipotez
ISA/SIA Loop (saatlik, 1-3 aday, küçük nudge)
    ↓ weight + parametre güncellemesi
Bot (canlı trading)
```

Her katman bir altındakine en iyi hipotezini devreder. LLM yoksa her katman mutation ladder'a fallback yapar.

---

## Hızlı Başlangıç

### Gereksinimler

- Python 3.12+
- Node.js 20+ (dashboard build için)
- Bir Polymarket hesabı ve API anahtarları (live trading için; paper mode'da gerekmez)

### Kurulum

```bash
# Repoyu klonla
git clone https://github.com/Talcawarrior/ASIAbot.git
cd ASIAbot

# Python bağımlılıkları
pip install -r requirements.txt

# Dashboard bağımlılıkları (npm install — node_modules .gitignore'da)
npm install

# .env yapılandırması
cp .env.example .env
# .env dosyasını düzenle (API anahtarları, tercihler)

# Veritabanı
python -c "from database.db import init_db; init_db()"
```

> ⚠️ **Önemli:** `npm install` çalıştırmazsanız bot açılırken dashboard build'i hata verir. Bot ilk açılışta `node_modules` yoksa otomatik `npm install` çalıştırır, ama elle yapmak daha hızlıdır.

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

> ⚠️ **Uyarı:** `ASIABOT_API_KEY` set edilmezse API açık modda çalışır — tüm POST endpoint'leri (reset, cleanup, start/stop) kimlik doğrulamasız çalışır. **Sadece localhost için güvenlidir.** `HOST=0.0.0.0` yapmadan önce mutlaka set edin.

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

### Hızlı Açılış (86 sn → 2 sn)

Bot açılış süresi 3 faktöre bağlıdır:

| Senaryo | Süre | Açıklama |
|---------|------|----------|
| **Cold start** (npm install + build) | ~30-86 sn | İlk açılış, `node_modules` + `out/` yok |
| **Warm start** (out/ + node_modules hazır) | ~2.5 sn | Normal açılış |
| **Skip build** (`SKIP_DASHBOARD_BUILD=true`) | ~2 sn | Production modu |

#### En Hızlı Açılış İçin

```bash
# 1. İlk sefer: npm install + build yap (bir kez)
npm install
npm run build

# 2. Sonraki açılışlarda: build'i atla
export SKIP_DASHBOARD_BUILD=true
python main.py bot

# veya .env'ye ekle:
echo "SKIP_DASHBOARD_BUILD=true" >> .env
python main.py bot
```

#### Neden Hızlı?

- **`SKIP_DASHBOARD_BUILD=true`** → `npx next build` tamamen atlanır (~25 sn tasarruf)
- **`npm ci`** (package-lock varsa) → `npm install`'dan 2-3x daha hızlı
- **`PER-5 warm-start`** → restart sonrası 47 şehir DB'den cache'e yüklenir (~60 sn tasarruf)
- **Paralel tarama** → `parse_markets` + `fetch_weather` aynı anda çalışır (~50 sn tasarruf)
- **`forecast_days=5`** → 14 yerine 5 gün (~10 sn tasarruf)

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
| `GET /api/status` | Bot durumu, portföy değeri, PnL, açık bahisler, Sharpe (rf dahil), MaxDD |
| `GET /api/health-check` | Kapsamlı sağlık kontrolü (edge dağılımı, red flags, 7 günlük PnL) |

### Piyasalar ve Bahisler

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/markets` | Tüm hava piyasaları + tahminler |
| `GET /api/bets` | Bahis geçmişi (status, limit, offset filtresi) |
| `GET /api/signals` | Açık pozisyonlar + canlı edge takibi (entry/live/move_pct) |
| `GET /api/history` | Kapanmış bahislerin W/L/ROI geçmişi (exit_price dahil) |
| `GET /api/equity-curve` | Günlük PnL serisi (portföy değeri zaman grafiği) |
| `GET /api/slippage` | Slippage tahmin kayıtları (model doğrulama) |
| `GET /api/asi/trades` | On-chain Polymarket trade verisi |
| `GET /api/asi/orderbook` | ResolvedMarkets'ten CLOB orderbook derinliği |

### ASI-Evolve

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/asi/weights` | Güncel model ağırlıkları + Brier + accuracy + trend (up/down/stable) |
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
| `WS /ws` | WebSocket canlı güncellemeler (scan_complete broadcast) |

> 🔒 = **Korunan endpoint**. `ASIABOT_API_KEY` env değişkeni set edildiğinde, bu endpoint'ler `X-API-Key` header'ı gerektirir. Set edilmezse API açık modda çalışır (sadece localhost için güvenli).

---

## Konfigürasyon

### `.env` Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DRY_RUN` | `true` | Gerçek emir göndermeden simülasyon (paper mode) |
| `LIVE_TRADING_ENABLED` | `false` | `DRY_RUN=false` + `true` → gerçek emir |
| `INITIAL_PORTFOLIO` | `1000.0` | Başlangıç portföy değeri ($) |
| `SCAN_INTERVAL` | `300` | Market tarama aralığı (saniye) |
| `SETTLEMENT_INTERVAL` | `120` | Settlement kontrol aralığı (saniye) |
| `MAX_EXPOSURE_PCT` | `0.25` | Maksimum toplam exposure (%25) |
| `MAX_BET_PCT` | `0.03` | Maksimum bet (portföy %3'ü; **dinamik %2-5** edge band'ine göre) |
| `MIN_BET_SIZE` | `1.0` | Minimum bet ($; Kelly < min/2 ise bet açılmaz) |
| `KELLY_FRACTION` | `0.15` | Fractional Kelly (**dinamik 0.10-0.25** edge band'ine göre) |
| `FLAT_BET_USD` | `0.0` | `>0` → sabit $ bet (Kelly override), `0` → Kelly sizing |
| `DAILY_LOSS_LIMIT` | `0.20` | Günlük zarar limiti (%20 — circuit breaker) |
| `CITY_CAP` | `4` | Şehir başına maksimum pozisyon |
| `FEE_DRAG` | `0.05` | Polymarket Weather taker fee (%5) |
| `REOPEN_COOLDOWN_HOURS` | `24` | TP/SL sonrası aynı markete re-entry cooldown (saat) |
| `HOST` | `127.0.0.1` | Sunucu adresi |
| `PORT` | `8091` | API portu |
| `ASIABOT_API_KEY` | — | API koruması için anahtar (yoksa açık mod) |

> **Not:** `MAX_BET_PCT` ve `KELLY_FRACTION` artık **dinamik** — `dynamic_max_bet_pct(edge)` ve `dynamic_kelly_fraction(edge)` fonksiyonları edge band'ine göre %2-5 ve 0.10-0.25 arası otomatik ayarlar. `.env`'deki değer base/orta band'dir.

### Risk Parametreleri

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `stop_loss_pct` | `0.20` | Stop-loss eşiği (%20 zarar — hızlı kayıp kesme) |
| `take_profit_pct` | `1.0` | Take-profit eşiği (%100 kâr) |
| `trailing_stop_pct` | `0.15` | Trailing stop eşiği (%15 gerileme) |
| `edge_erosion` | `min_edge/2` | Edge erozyonu eşiği (şimdi %10) |
| `model_reversal` | `0.20` | Model ters dönme eşiği (%20 prob değişimi) |
| `MIN_HOLD_MINUTES` | `3` | Minimum bekleme süresi (dakika) |

### LLM Yapılandırması (Opsiyonel)

```env
ZAI_API_KEY=anahtar                          # Z.AI API anahtarı (yoksa mutation ladder fallback)
ZAI_BASE_URL=https://api.z.ai/api/paas/v4/   # API base URL
LLM_MODEL=glm-4.5-flash                       # Model adı
```

> LLM opsiyoneldir — API key yoksa tüm 3 katman (Karpathy/ASI-Evolve/SIA-Hourly) mutation ladder'a fallback yapar.

### Strateji Parametreleri

Parametreler iki kaynaktan gelir: `data/strategy_params.json` (Karpathy/SIA tarafından güncellenir) ve `config/settings.py` (varsayılanlar):

| Parametre | Varsayılan | Kaynak | Açıklama |
|-----------|-----------|--------|----------|
| `min_edge` | `0.20` | `strategy_params.json` | Minimum net edge eşiği (%20) |
| `kelly_fraction` | `0.15` | `strategy_params.json` | Base fractional Kelly (dinamik band: 0.10-0.25) |
| `min_days_ahead` | `1` | `settings.py` | Minimum gün sayısı (same-day bet'leri engeller; 0=bugün, 1=yarın, 2=öbür gün) |
| `max_days_ahead` | `2` | `settings.py` | Maksimum gün sayısı (2+ gün ileri piyasaları atlar) |
| `min_entry_price` | `0.01` | `settings.py` | Minimum giriş fiyatı (Karpathy-tuned: 0.35) |
| `inefficiency_min` | `-1.0` | `settings.py` | Minimum verimsizlik (Karpathy-tuned: -0.124) |
| `slippage_model` | `orderbook` | `settings.py` | Slippage modeli: flat / tiered / orderbook |
| `min_depth_usd` | `0.0` | `settings.py` | Min orderbook derinliği ($; 0 = disabled) |

### Midnight Scan

Gece yarısı sonrası bot, 2 gün ileri tarihli piyasaları erken yakalamak için özel tarama moduna geçer:

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `midnight_scan_interval` | `60` | Tarama aralığı (saniye) |
| `midnight_scan_window` | `60` | Tarama süresi (dakika) |

---

## Modeller

SIA Loop tarafından optimize edilen 8 hava modeli (tek Open-Meteo çağrısı ile gelir):

| Model | Kaynak | Default Weight |
|-------|--------|---------------|
| GFS Seamless | NOAA | ~%12.2 |
| ECMWF IFS 0.25 | ECMWF | ~%12.4 |
| GEM Global | Environment Canada | ~%12.5 |
| ICON Global | DWD (Almanya) | ~%12.9 |
| JMA Seamless | Japan Meteorological Agency | ~%12.8 |
| CMA Grapes Global | China Meteorological Administration | ~%12.3 |
| UKMO Seamless | UK Met Office | ~%12.0 |
| Météo-France Seamless | Météo-France | ~%12.9 |

> **Not:** Ağırlıklar SIA tarafından saatlik Brier skoruna göre optimize edilir. Yukarıdaki değerler güncel `data/model_weights.json` içeriğidir (uniform başlangıç → SIA henüz ayrıştırmamış). `MIN_MODEL_WEIGHT=0.05` floor uygulanır.

---

## Duplicate Bet Önleme

Bot, aynı markete tekrar bet açmayı 3 katmanlı koruma ile engeller:

### 1. `no_existing_bet` Gate (place_bet içinde)
- Aynı `market_id`'de aktif bet varsa (`OPEN_BET_STATUSES`: active/open/placed/pending)
- Aynı gün açılmış bet varsa (`placed_at >= today_start`)

### 2. Cooldown (REOPEN_COOLDOWN_HOURS)
- TP/SL/trailing ile kapanan bet (`closed_early`) → 24 saat re-entry engeli
- Settled bet (won/lost) → 24 saat re-entry engeli
- `closed_at >= now - 24h` veya `settled_at >= now - 24h` clause

### 3. City+Threshold Dedup (place_all_pending)
- Aynı şehir + aynı metric + aynı threshold + aynı date → engelle

### Senaryo: Ankara Yarın 25°C

| Durum | Açılır mı? |
|-------|-----------|
| Aktif bet var | ❌ HAYIR |
| Bugün açılmış bet var | ❌ HAYIR |
| TP ile kapandı, 1 saat sonra | ❌ HAYIR (cooldown) |
| TP ile kapandı, 24 saat sonra | ❌ HAYIR (cooldown) |
| TP ile kapandı, 25 saat sonra | ✅ EVET (cooldown bitti) |

> "Bir daha hiç açılmasın" istenirse: `REOPEN_COOLDOWN_HOURS=8760` (1 yıl) set edin.

---

## Bet Açma Gate'leri (13 adım)

`place_bet()` sırasıyla şu gate'leri kontrol eder:

1. `analysis_exists` — Analysis kaydı var ve `should_bet=True`
2. `edge_positive` — Edge > `bot_config.strategy.min_edge` (canlı min_edge, SIA/Karpathy ayarlar)
3. `market_exists` — WeatherMarket bulundu
4. `daily_loss_limit` — Circuit breaker tetiklenmedi
5. `price_valid` — Binary price geçerli (0.01-0.99)
6. `target_date_ok` — Target date gelecekte
7. **`min_days_ahead`** — `min_days_ahead <= days_ahead <= max_days_ahead` (same-day engeli; varsayılan: 1-2 gün)
8. `min_entry_price` — Fiyat ≥ `bot_config.strategy.min_entry_price` (long-shot filter)
9. `max_entry_price` — Fiyat ≤ 0.97 (çok yüksek fiyata girme)
10. **`no_existing_bet`** — Duplicate önleme (cooldown dahil)
11. `exposure_cap` — Toplam exposure ≤ %25 × conservative portfolio
12. `city_cap` — Şehir başına < 4 bet
13. `depth_ok` — Orderbook derinliği yeterli (resolvedmarkets_ingest gerçek API)

Tüm gate'leri geçen adaylar **tier-based priority** ile sıralanır:
- **Tier 3** (2+ gün sonra): en yüksek öncelik — erken pozisyon avantajı
- **Tier 2** (1+ gün sonra): orta öncelik
- **Tier 1** (bugün): düşük öncelik
- Aynı tier'da edge'i yüksek olan önce açılır

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

# Tüm testler (330 test)
PYTHONPATH=. pytest

# Coverage
coverage run -m pytest
coverage report

# Pre-commit (otomatik çalışır)
pre-commit run --all-files

# Full pipeline
ruff check . && mypy . && pytest
```

### Test Yapısı (43 dosya, 330 test)

```
tests/
├── test_accounting.py               # Portföy muhasebe testleri
├── test_active_risk_management.py   # Risk yönetimi (stop-loss, TP, trailing)
├── test_api_bets.py                 # API bahis endpoint testleri
├── test_api_integration.py          # API entegrasyon testleri
├── test_asi_evolve.py               # ASI-Evolve testleri
├── test_calculator.py               # Hava durumu hesaplama
├── test_calculator_min_edge.py      # Edge eşiği testleri
├── test_calculator_real.py          # Gerçek veri ile hesap
├── test_config_consistency.py       # Config tutarlılık
├── test_ev_fix_and_audit.py         # EV FIX + 16 hata denetim testleri (YENİ)
├── test_faz2_e2e_mock.py .. 6.py    # End-to-end mock testleri
├── test_karpathy_weekly.py          # Karpathy search testi
├── test_kelly_wrapper_regression.py # Kelly wrapper regresyon
├── test_live_data_smoke.py          # Canlı veri smoke testi
├── test_llm_loop_orchestrator.py    # LLM loop testleri
├── test_meteo.py                    # Open-Meteo testleri
├── test_meteo_cache_ttl.py          # Cache TTL testleri
├── test_polymarket_mock.py          # Polymarket mock testleri
├── test_polymarket_real.py          # Polymarket gerçek testleri
├── test_researcher_agent_honesty.py # Araştırma agent dürüstlük
├── test_sia_hourly.py               # SIA Loop testleri
├── test_signals_active_positions.py # Açık pozisyon sinyal testleri
├── test_slippage.py                 # Slippage modeli
└── test_weights_store.py            # Ağırlık depolama
```

---

## Proje Yapısı

```
ASIAbot/
├── asi_engine/          # ASI-Evolve: calibration, cognition, evolving, karpathy
├── config/              # Settings, logging
├── data/                # Runtime veri (weights, params, backtest, calibration)
├── data_pipeline/       # Polymarket + ResolvedMarkets veri çekme
├── database/            # SQLAlchemy ORM (Bet, Portfolio, Analysis, WeatherMarket)
├── engine/              # Core: calculator, strategy, risk manager, decision
├── executor/            # BetPlacer, Settlement
├── jobs/                # Zamanlanmış görevler (scheduler)
├── scrapers/            # Polymarket, Open-Meteo, async_client (cache+throttle)
├── scripts/             # Diagnostic/utility script'ler
├── src/                 # Next.js dashboard (app/, lib/, components/)
├── tests/               # 330 test (43 dosya)
├── utils/               # Kelly, slippage, probability, accounting, formulas
├── main.py              # Bot + API + CLI giriş noktası
├── api.py               # FastAPI endpoint'leri
├── bot_loop.py          # Bot döngüsü + midnight scan + WebSocket broadcast
├── .pre-commit-config.yaml  # Pre-commit hooks
├── mypy.ini             # Mypy yapılandırması
└── pyrightconfig.json   # Pyright yapılandırması
```

---

## Performans

Bot açılış hızı için optimizasyonlar:

| Optimizasyon | Kazanım |
|-------------|---------|
| Paralel tarama (`asyncio.gather` parse + weather) | ~50 sn |
| Weather Semaphore 8→20, throttle 2.5s→1.0s | ~16 sn |
| `forecast_days` 14→5 (bot 0-2 gün ileri marketleri işler) | ~10 sn |
| `WeatherEngine.warm_start_from_db()` — restart sonrası DB'den yükle | ~60 sn |
| AsyncHttpClient 5dk TTL cache (Polymarket sorguları) | ~30 sn |
| Next.js build CI'da (runtime'da değil) | 60-120 sn |

---

## Formüller (Tek Kaynak)

Tüm finansal hesaplamalar `utils/formulas.py`'den gelir:

- `max_bet_cap(portfolio, pct)` — per-bet cap
- `conservative_portfolio_value(initial, realized)` — feedback loop önleme
- `max_exposure_cap(initial, realized, pct)` — toplam exposure
- `unrealized_pnl(shares, current, entry)` — açık pozisyon PnL
- `settlement_pnl(stake, entry, fee, won)` — settled PnL
- `polymarket_fee(shares, price, rate)` — resmi `C × feeRate × p × (1-p)`
- `portfolio_total_value(cash, exposure)` — book value
- `portfolio_current_value(initial, realized, unrealized)` — market value

**Kelly:** `utils/kelly.py` — `kelly_fraction(prob, price)` + `kelly_bet_amount(portfolio, prob, price, edge=...)`

---

## Changelog

### 2026-07-08 — min_days_ahead + days_ahead SQLite Bug Fix

**Değişiklikler:**
1. **`config/settings.py`** — `StrategyConfig`'e `min_days_ahead: int = 1` eklendi. Same-day (day-0) bet'leri artık reddedilir; bot sadece 1-2 gün ileri piyasalarda işlem yapar.
2. **`engine/calculator.py`** — `days_ahead` hesaplaması **SQLite microsecond truncation** bug'ı düzeltildi: `timedelta.days` yerine takvim tarih farkı `(target_date.date() - now.date()).days` kullanılıyor. Önceki kodda 23saat59dakika kalan bir piyasa `days_ahead=0` olarak hesaplanıyordu.
3. **`engine/calculator.py`** — `should_bet` gate'i güncellendi: `0 <= days_ahead <= max` → `min_days_ahead <= days_ahead <= max_days_ahead`.
4. **`engine/calculator.py`** — Reddedilen bahisler için yeni sebep: `"Çok yakın: X gün (min=Y)"`.
5. **`tests/test_days_ahead_regression.py`** — Test, yeni `min_days_ahead` check kod yapısına güncellendi.
6. **Blend weight fix** (devamı): `blend_weight` hardcoded seed'leri 0.65→0.45, SIA "+0.03" boost kaldırıldı, Karpathy "+0.15" rung silindi, max clamp 1.0→0.50.

**Test:** 330/330 passed

### 2026-07-07 — 5 Bug Fix + Continuous Calibration

**Değişiklikler:**
1. **`asi_engine/calibration_engine.py`** — Tamamen yeniden yazıldı:
   - **Rolling window:** Son 60 gün veri, eski model versiyonlarının bias'ı kullanılmaz
   - **Recency weighting:** 14 gün yarı ömürlü üstel ağırlıklandırma
   - **Shrinkage:** 20+'dan az gözlemde bias 0'a çekme (`trust_factor = min(count/20, 1.0)`)
   - **Boş veri koruması:** Son 60 günde hiç veri yoksa eski harita korunur (`return self.bias_map`)
   - **`_parse_dt()`:** Çoklu SQLite tarih formatı desteği
2. **`engine/strategy.py`** — `run_optimization_cycle()`'a **Adım 0** eklendi: kalibrasyon artık her SIA döngüsünde otomatik tazelenir, manuel API çağrısı gerekmez
3. **BUG-1 (dead-code):** `scrapers/meteo_cache.py` silindi — hiçbir yerde import edilmiyor, `meteo.py` kendi içinde aynı cache'i taşıyor
4. **BUG-2 (concurrency):** `scrapers/meteo.py _throttle()` — `asyncio.get_running_loop()` + `loop.run_until_complete()` kaldırıldı, direkt `time.sleep()`. Çalışan event loop üzerinde `run_until_complete` tüm taskları donduruyordu
5. **BUG-3 (performance):** `engine/market_parser.py parse_all_unparsed()` — 714 ayrı session/commit yerine **1 session + 1 commit**. `PolymarketScraper` her market için yeniden oluşturulmuyor (1 kez `__init__`'de)
6. **BUG-4 (cosmetic):** `database/models.py` — duplicate `Market = WeatherMarket` satırı silindi
7. **BUG-5 (redundant):** `jobs/scheduler.py run_cycle()` — gereksiz `session.commit()` silindi, `get_session()` with bloğu çıkışında auto-commit yapıyor

**Test:** 329/330 passed (1 pre-existing failure: `KELLY_FRACTION` mismatch — conftest.py singleton mutation vs fresh instance default)

### 2026-07-09 — min_edge %5 → %20; prioritization doğrulaması

**Değişiklikler:**
1. **`executor/bet_placer.py`** — `_priority_key()` **değişmedi**, tier-first sıralama korundu:
   - En uzak tarih (Tier 3, 2+ gün) en önce açılır
   - Aynı tier'da en yüksek EV önce açılır
   - Bu, bot'un erken pozisyon avantajını koruması içindir

**Neden:** Edge <%25 tüm dilimler net zarardaydı (eski analiz):
| Edge Aralığı | Bet Sayısı | P&L |
|---|---|---|
| %0-%5 | 45 | -$58.98 |
| %5-%10 | 109 | -$44.17 |
| %10-%20 | 80 | -$29.21 |
| %20-%25 | 88 | +$9.43 |
| **Toplam <%25** | **344** | **-$127.96** |
| **≥%25** | **369** | **+$587.60** |

## Lisans

MIT
