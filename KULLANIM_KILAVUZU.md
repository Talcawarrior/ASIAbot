# ASIAbot Kullanım Kılavuzu

**Polymarket Hava Tahmin Piyasaları için Kendini Geliştiren Yapay Zeka Botu**

---

## İçindekiler

1. [Gereksinimler](#1-gereksinimler)
2. [Kurulum](#2-kurulum)
3. [Yapılandırma (.env)](#3-yapılandırma-env)
4. [Botu Başlatma](#4-botu-başlatma)
5. [Mimari Genel Bakış](#5-mimari-genel-bakış)
6. [API Endpoint'leri](#6-api-endpointleri)
7. [ISA/SIA Loop (Saatlik)](#7-isasia-loop-saatlik)
8. [ASI-Evolve (Günlük)](#8-asi-evolve-günlük)
9. [Karpathy Search (Manuel)](#9-karpathy-search-manuel)
10. [Risk Yönetimi](#10-risk-yönetimi)
11. [Kelly Sizing ve Bet Büyüklüğü](#11-kelly-sizing-ve-bet-büyüklüğü)
12. [Ladder Sistemi](#12-ladder-sistemi)
13. [Slippage Modeli](#13-slippage-modeli)
14. [Erken Çıkış Stratejileri](#14-erken-çıkış-stratejileri)
15. [Duplicate Bet Önleme](#15-duplicate-bet-önleme)
16. [Portföy Muhasebesi](#16-portföy-muhasebesi)
17. [Formüller (Tek Kaynak)](#17-formüller-tek-kaynak)
18. [Test Çalıştırma](#18-test-çalıştırma)
19. [Troubleshooting](#19-troubleshooting)
20. [Sık Sorulan Sorular](#20-sık-sorulan-sorular)

---

## 1. Gereksinimler

- **Python:** 3.12+
- **Node.js:** 20+ (dashboard build için, opsiyonel)
- **Bağımlılıklar:** `pip install -r requirements.txt`
- **Polymarket hesabı:** Paper trade için gerekmez, live trade için cüzdan + API key
- **Z.AI API key:** LLM katmanları için opsiyonel (yoksa mutation ladder fallback)

## 2. Kurulum

```bash
# 1. Repoyu klonla
git clone <repo-url> ASIAbot
cd ASIAbot

# 2. Python bağımlılıklarını yükle
pip install -r requirements.txt

# 3. Ortam değişkenlerini ayarla
cp .env.example .env
# .env dosyasını düzenle (ZAI_API_KEY, vb.)

# 4. Dashboard build (opsiyonel — bot build'siz de çalışır)
# src/ dizininde değişiklik yaptıysan:
cd src
npm install
npx next build
cd ..
```

## 3. Yapılandırma (.env)

Tüm yapılandırma `.env` dosyasından okunur. Zorunlu alanlar:

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `DRY_RUN` | `true` | `true` = paper trade, `false` = live Polymarket |
| `INITIAL_PORTFOLIO` | `1000.0` | Başlangıç portföy büyüklüğü ($) |
| `PORT` | `8091` | Dashboard/API portu |
| `HOST` | `127.0.0.1` | Bağlantı adresi |
| `SKIP_DASHBOARD_BUILD` | `false` | `true` = build atla (hızlı açılış) |

**Risk parametreleri:**

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `MAX_BET_PCT` | `0.03` | Maksimum tek bet büyüklüğü (portföyün %3'ü) |
| `MAX_EXPOSURE_PCT` | `0.25` | Toplam exposure limiti (portföyün %25'i) |
| `KELLY_FRACTION` | `0.15` | Fractional Kelly çarpanı |
| `CITY_CAP` | `4` | Aynı şehirde maksimum açık bet sayısı |
| `MIN_BET_SIZE` | `1.0` | Minimum bet büyüklüğü ($) |
| `FLAT_BET_USD` | `0.0` | Sabit bet büyüklüğü (0 = Kelly kullan) |
| `DAILY_LOSS_LIMIT` | `0.20` | Günlük kayıp limiti (portföyün %20'si) |
| `FEE_DRAG` | `0.05` | Varsayılan Polymarket fee oranı (%5) |
| `REOPEN_COOLDOWN_HOURS` | `24` | TP/SL sonrası re-entry bekleme süresi |
| `LIVE_TRADING_ENABLED` | `false` | `true` = gerçek Polymarket emirleri gönder |

**LLM yapılandırması (opsiyonel):**

```
ZAI_API_KEY=<id.secret>          # Z.AI API anahtarı
ZAI_BASE_URL=https://api.z.ai/api/paas/v4/
LLM_MODEL=glm-4.5-flash
```

**Not:** LLM API key yoksa bot yine çalışır — tüm LLM katmanları (Karpathy, ASI-Evolve, SIA) **deterministic mutation ladder**'a fallback yapar.

## 4. Botu Başlatma

### Ana komutlar

```bash
# Tam bot (scan + API + Dashboard + background loops)
python main.py bot

# Sadece API + Dashboard (arka plan döngüsü yok)
python main.py run
```

Bot başladığında:
1. **FastAPI** `http://localhost:8091` adresinde başlar
2. **Next.js Dashboard** aynı portta serve edilir
3. **WebSocket** `/ws` endpoint'inden scan_complete broadcast yayınlar
4. **SIA Loop** saatlik otomatik çalışır
5. **Settlement** 120sn aralıkla kapanan piyasaları kontrol eder

### Tek seferlik işlemler

```bash
python main.py fetch       # Polymarket'ten açık piyasaları tara
python main.py weather     # Open-Meteo'dan hava tahminlerini çek
python main.py analyze     # Marketleri analiz et (edge hesapla)
python main.py bet         # Uygun bet'leri aç
python main.py settle      # Settlement kontrolü yap
python main.py report      # Rapor oluştur

# LLM katmanları
python main.py llm karpathy      # Karpathy Search (haftalık)
python main.py llm asi_evolve    # ASI-Evolve (günlük)
python main.py llm sia           # SIA Loop (saatlik)
python main.py llm status        # LLM katman durumu
```

### API üzerinden kontrol

```bash
# Bot'u başlat/durdur
curl -X POST http://localhost:8091/api/start -H "X-API-Key: <key>"
curl -X POST http://localhost:8091/api/stop -H "X-API-Key: <key>"
curl -X POST http://localhost:8091/api/reset -H "X-API-Key: <key>"

# ASI-Evolve çalıştır
curl -X POST http://localhost:8091/api/asi/evolve -H "X-API-Key: <key>"
```

> **API Key:** Eğer `.env`'de `ASIABOT_API_KEY` set edilmişse, POST endpoint'leri `X-API-Key` header'ı gerektirir. Key yoksa API açık modda çalışır (sadece localhost).

## 5. Mimari Genel Bakış

```
ASIAbot/
├── asi_engine/          # Yapay zeka katmanları
│   ├── sia_hourly.py    #   SIA Loop (saatlik ağırlık optimizasyonu)
│   ├── asi_evolve.py    #   ASI-Evolve (günlük genetik evrim)
│   ├── karpathy_weekly.py  # Karpathy Search (manuel/opsiyonel)
│   ├── cognition_base.py   # ASI bilişsel temel (distilled insights)
│   ├── calibration.py      # Şehir bazlı bias kalibrasyonu
│   ├── orchestrator.py     # ASI-Evolve orkestratörü
│   └── llm_loop_orchestrator.py  # 3-katmanlı LLM koordinatörü
├── config/              # settings.py + logging
├── data/                # Runtime veri (weights, params, backtest)
├── data_pipeline/       # Polymarket + ResolvedMarkets veri çekme
├── database/            # SQLAlchemy ORM (Bet, Portfolio, Analysis, WeatherMarket)
├── engine/              # Core mantık
│   ├── calculator.py    #   Edge/EV hesaplama, slippage, fee
│   ├── strategy.py      #   RiskManager, SIALoop, sinyal analizi
│   └── decision.py      #   BetDecision (gate geçiş kaydı)
├── executor/            # BetPlacer + Settlement
├── jobs/                # Zamanlanmış görevler
├── scrapers/            # Polymarket, Open-Meteo, async_client
├── src/                 # Next.js 16 Dashboard
├── tests/               # 330 test (43 dosya)
├── utils/               # Kelly, slippage, probability, accounting, formulas
├── main.py              # CLI + Bot giriş noktası
└── api.py               # FastAPI (tüm endpoint'ler)
```

### Veri Akışı

```
1. FETCH    → Polymarket gamma-api ile açık hava piyasalarını tara
                (tarih bazlı sorgular: bugün + 2 gün ileri)
2. WEATHER  → Open-Meteo API'den 8 modelin tahminlerini çek
                (tek çağrı, 5 gün forecast, 20 paralel city)
3. WEIGHT   → SIA ağırlıkları ile weighted ensemble hesapla
4. CALIBRATE→ Kalibrasyon düzeltmesi uygula (şehir bazlı bias)
5. ANALYZE  → Edge = model_prob - market_price
                net_edge = raw - slippage - fee - gas
6. SIZE     → Dinamik Kelly: kelly_bet_amount(edge=...)
                3 band: >=%20 → %5 cap, %10-20 → %3 cap, <%10 → %2 cap
7. PLACE    → 3 kademeli ladder + 12 gate + 3 cap
8. SETTLE   → Settlement sonrası PnL güncelle, SIA feedback
9. ARCHIVE  → Hot DB (10g) → Cold Parquet (10-120g) → Purge (>120g)
```

## 6. API Endpoint'leri

| Endpoint | Metot | Açıklama |
|----------|-------|----------|
| `/` | GET | Dashboard (Next.js static export) |
| `/api/status` | GET | Bot durumu, portföy, istatistikler |
| `/api/markets` | GET | Açık piyasalar + missed signal'lar |
| `/api/bets?status=&limit=&offset=` | GET | Bet geçmişi (filtreleme + pagination) |
| `/api/signals` | GET | Aktif (açık) pozisyonlar |
| `/api/history` | GET | Kapanmış bet'ler (win/loss stats) |
| `/api/equity-curve` | GET | Günlük equity curve (PnL) |
| `/api/slippage` | GET | Son slippage verileri |
| `/api/health-check` | GET | Kapsamlı sağlık kontrolü |
| `/api/asi/weights` | GET | Model ağırlıkları + performans |
| `/api/asi/cognition` | GET | ASI cognition base insights |
| `/api/asi/calibration` | GET | Bias kalibrasyon haritası |
| `/api/asi/orderbook?market_id=` | GET | CLOB orderbook derinliği |
| `/api/asi/trades` | GET | On-chain trade verisi |
| `/api/start` | POST | Bot'u başlat |
| `/api/stop` | POST | Bot'u durdur |
| `/api/reset` | POST | Sistemi sıfırla |
| `/api/cleanup` | POST | Stale bet'leri temizle |
| `/api/asi/evolve` | POST | ASI-Evolve çalıştır |
| `/api/asi/backfill?days=90` | POST | Geçmiş veri backfill |
| `/api/asi/calibration/recalculate` | POST | Kalibrasyonu yeniden hesapla |

**WebSocket:** `/ws` — `scan_complete` event'ini broadcast eder. Frontend 10sn polling + 60sn fallback kullanır.

**Status Response (örnek):**

```json
{
  "is_running": true,
  "portfolio": {
    "initial": 1000,
    "current": 1469.18,
    "total_pnl": 469.18,
    "exposure": 176.79,
    "max_exposure": 250.0
  },
  "stats": {
    "total_signals": 950,
    "total_bets": 11,
    "win_count": 359,
    "loss_count": 370,
    "total_closed": 729
  },
  "limits": {
    "max_bet_pct": 3.0,
    "max_exposure_pct": 25.0,
    "city_cap": 4
  }
}
```

## 7. ISA/SIA Loop (Saatlik)

**Dosya:** `asi_engine/sia_hourly.py`
**Çalışma sıklığı:** Saatte bir (bot çalışırken otomatik)

### Ne iş yapar?

SIA (Self-Improving Agent), açık piyasalardan gelen gerçek sonuçlara göre **8 hava modelinin ağırlıklarını optimize eder:**

1. **Weight Update:** Her modelin Brier skorunu hesaplar, düşük Brier = yüksek weight
2. **Harness Update:** Strateji parametrelerini finansal performansa göre ayarlar:
   - Win Rate düşükse (< %50) → `min_edge` artır (daha seçici)
   - Win Rate yüksekse (> %60) + ROI pozitifse → `min_edge` azalt (daha fazla trade)
   - Büyük drawdown'da (< -%10 ROI) → `kelly_fraction` azalt
3. **LLM opsiyonel:** Z.AI API key varsa LLM'den hipotez ister, yoksa mutation ladder

### Model Ağırlıkları

Başlangıçta uniform (%12.5), SIA saatlik optimize eder:

| Model | Kaynak | Varsayılan Weight |
|-------|--------|------------------|
| GFS Seamless | NOAA | ~%12.2 |
| ECMWF IFS 0.25 | ECMWF | ~%12.4 |
| GEM Global | Environment Canada | ~%12.5 |
| ICON Global | DWD (Almanya) | ~%12.9 |
| JMA Seamless | Japan Meteorological Agency | ~%12.8 |
| CMA Grapes Global | China Meteorological Administration | ~%12.3 |
| UKMO Seamless | UK Met Office | ~%12.0 |
| Météo-France Seamless | Météo-France | ~%12.9 |

> **Not:** `MIN_MODEL_WEIGHT=0.05` floor uygulanır — hiçbir modelin ağırlığı %5'in altına düşmez.

### Çıktılar

- `data/model_weights.json` — Güncel ağırlıklar
- `data/sia_hourly_best.json` — En iyi hipotez
- `data/sia_hourly_results.tsv` — Tüm denemeler

## 8. ASI-Evolve (Günlük)

**Dosya:** `asi_engine/asi_evolve.py`
**Çalışma sıklığı:** Günlük (manuel veya API ile)

### Ne iş yapar?

Genetik algoritma ile strateji evrimi:

1. **UCB1 Selection:** En umut verici hipotezleri seç
2. **Crossover:** İki başarılı hipotezi çaprazla
3. **Mutation Ladder:** Rastgele mutasyon uygula (min_edge, kelly, model weights)
4. **Walk-Forward OOS:** Temporal leakage önleyen backtest ile değerlendir
5. **Accept/Reject:** Sharpe oranı iyiyse kabul et, veriyi cognition_base'e ekle

### Kullanım

```bash
# Manuel çalıştırma
python main.py llm asi_evolve

# API üzerinden
curl -X POST http://localhost:8091/api/asi/evolve -H "X-API-Key: <key>"
```

### Bağımlılıklar

- **Karpathy Search** çıktısını tüketir (en iyi hipotezi seed olarak kullanır)
- **Data Backfiller** ile geçmiş veriyi kullanır
- **Cognition Base**'e yeni insight'lar ekler

## 9. Karpathy Search (Manuel)

**Dosya:** `asi_engine/karpathy_weekly.py`
**Çalışma sıklığı:** Manuel (otomatik cron/scheduler yok)

### Ne iş yapar?

Karpathy-style genetik arama ile **strateji parametrelerini** geniş bir uzayda tarar:

- **min_edge:** 0.02-0.50 arası
- **kelly_fraction:** 0.05-0.50 arası
- **min_entry_price:** 0.01-0.50 arası  
- **inefficiency_min:** -0.50 ile 0 arası
- **Model weights:** 8 model için ayrı ayrı

Walk-forward OOS doğrulama kullanır — temporal leakage yok. En iyi hipotezi `data/karpathy_best.json`'a kaydeder.

### Kullanım

```bash
# 6 round çalıştır (varsayılan)
python main.py llm karpathy

# LLM ile çalıştır (ZAI_API_KEY gerekli)
python main.py llm karpathy --llm

# Round sayısını belirle
python main.py llm karpathy --rounds 10

# Doğrudan modül olarak
python -m asi_engine.karpathy_weekly --rounds 6
```

### Çıktılar

- `data/karpathy_best.json` — En iyi hipotez
- `data/karpathy_results.tsv` — Tüm denemeler
- `data/strategy_params.json` — Kabul edilen parametreler

> **⚠️** Karpathy, Karpathy'nin "Simple Scaling" makalesindeki yaklaşımı taklit eder. Trade verisi birikince hipotez kabul eder. Şu an hazır durumda — yeterli veri birikince aktif hipotez üretmeye başlar.

## 10. Risk Yönetimi

### 12 Gate (Bet Açma Kontrolleri)

Her bet açılışında sırasıyla kontrol edilir:

| # | Gate | Açıklama |
|---|------|----------|
| 1 | `analysis_exists` | Analysis kaydı var ve `should_bet=True` |
| 2 | `edge_positive` | Edge > `min_edge` (SIA/Karpathy ile dinamik) |
| 3 | `market_exists` | WeatherMarket bulundu |
| 4 | `daily_loss_limit` | Circuit breaker tetiklenmedi (günlük kayıp limiti) |
| 5 | `price_valid` | Binary price geçerli (0.01-0.99) |
| 6 | `target_date_ok` | Target date gelecekte |
| 7 | `min_entry_price` | Fiyat ≥ minimum giriş fiyatı (long-shot filter) |
| 8 | `max_entry_price` | Fiyat ≤ 0.97 (çok yüksek fiyata girme) |
| 9 | `no_existing_bet` | Duplicate önleme (cooldown dahil) |
| 10 | `exposure_cap` | Toplam exposure ≤ %25 × conservative portfolio |
| 11 | `city_cap` | Şehir başına < 4 bet |
| 12 | `depth_ok` | Orderbook derinliği yeterli |

### 3 Cap (Limitler)

1. **Per-bet cap:** `min(proposed_amount, conservative_portfolio × dynamic_max_bet_pct)`
   - Edge ≥ %20 → %5 cap
   - Edge %10-%20 → %3 cap
   - Edge < %10 → %2 cap
2. **Exposure cap:** Toplam açık pozisyon ≤ conservative_portfolio × %25
3. **City cap:** Aynı şehirde maksimum 4 açık bet

### 7 Erken Çıkış (Early Exit)

Açık bet'leri koşullara göre otomatik kapatır:

| # | Strateji | Tetikleyici |
|---|----------|-------------|
| 1 | `take_profit` | Fiyat ≥ entry × (1 + TP threshold) |
| 2 | `stop_loss` | Fiyat ≤ entry × (1 - SL threshold) |
| 3 | `trailing_stop` | Peak'ten %15 düşüş |
| 4 | `time_decay` | Target date'e çok yakın (margin erir) |
| 5 | `edge_erosion` | Edge < min_edge/2'ye düştü |
| 6 | `model_reversal` | Model probability %20+ ters döndü |
| 7 | `stale_cleanup` | 24h+ açık pozisyon (API/cleanup ile) |

### Circuit Breaker

Günlük kayıp limiti aşılırsa (`DAILY_LOSS_LIMIT = %20`), o gün için yeni bet açılmaz.

### Conservative Portfolio

Portföy değeri hesaplanırken **unrealized PnL dahil edilmez**, sadece `initial + realized` kullanılır. Bu, feedback loop'u önler (açık pozisyonlardaki unrealized kâr portföyü şişirip daha fazla bet açtırmaz).

## 11. Kelly Sizing ve Bet Büyüklüğü

### Formül

Kelly percentage: `f* = (p × odds - 1) / (odds - 1)` 
Burada `odds = 1 / price` ve `p = model_probability`

Fractional Kelly: `bet_amount = portfolio × kelly_fraction × f*`

### Dinamik Band'ler

| Edge Aralığı | max_bet_pct | Kelly Fraction | Mod |
|-------------|-------------|----------------|-----|
| ≥ %20 | %5 | 0.25 | Pyramiding (kazanana ekle) |
| %10 - %20 | %3 | 0.15 | Averaging (maliyet düşür) |
| < %10 | %2 | 0.10 | Conservative |

**Kaynak kod:** `utils/kelly.py`

## 12. Ladder Sistemi

Her bet 3 kademeli ladder olarak açılır:

### Yüksek Edge (≥ %20) — Pyramiding

- L1: %70 (anında dolar) — agresif giriş
- L2: %20, fiyat × 1.02 (fiyat yükselince dolar)
- L3: %10, fiyat × 1.05

### Orta Edge (%10 - %20) — Averaging Down

- L1: %50 (anında dolar)
- L2: %30, fiyat × 0.98 (fiyat düşünce dolar)
- L3: %20, fiyat × 0.95

### Düşük Edge (< %10) — Conservative

- L1: %40 (anında dolar)
- L2: %35, fiyat × 0.98
- L3: %25, fiyat × 0.95

> L1 anında dolar, L2/L3 fiyat koşulu sağlanınca `run_update_prices` döngüsünde dolar.

**Kaynak kod:** `executor/bet_placer.py`

## 13. Slippage Modeli

3 kademeli slippage modeli (`utils/slippagepy`):

| Model | Açıklama |
|-------|----------|
| `flat` | Sabit % (varsayılan %0.5) |
| `tiered` | Fiyat bazlı: < $0.05 → %3, $0.05-$0.10 → %1, > $0.10 → %0.5 |
| `orderbook` | Gerçek CLOB derinliğinden VWAP fill (ResolvedMarkets API) |

Üretimde `orderbook` modeli kullanılır. API anahtarı yoksa graceful degradation ile `tiered`'e düşer.

**Net edge formülü:**
```
net_edge = raw_edge - slippage_pct - fee_drag - gas_cost
```

Burada:
- `fee_drag = FEE_PCT × entry_price × (1 - entry_price)` (Polymarket resmi fee formülü)
- `gas_cost = $0.10 / bet_amount × entry_price`

**Kaynak kod:** `utils/slippage.py`, `utils/formulas.py`

## 14. Erken Çıkış Stratejileri

```
RiskManager (engine/strategy.py)
├── take_profit():     entry_price × 2.0 → kapat
├── stop_loss():       entry_price × 0.8 → kapat
├── trailing_stop():   max_price'ten %15 düşüş → kapat
├── time_decay():      target_date'e < 3 saat → kapat
├── edge_erosion():    edge < min_edge/2 → kapat
└── model_reversal():  model_prob > %20 ters → kapat
```

Erken çıkan bet'ler `closed_early` statüsü alır ve `close_reason` ile işaretlenir (TP/SL/TS/TD/ER/MR). REOPEN_COOLDOWN_HOURS penceresi içinde aynı markete tekrar girilmez.

## 15. Duplicate Bet Önleme

3 katmanlı koruma:

1. **no_existing_bet gate (place_bet içinde):**
   - Aynı `market_id`'de aktif bet varsa engelle
   - Aynı gün açılmış bet varsa engelle
   - Son N saatte (cooldown) kapanmış bet varsa engelle

2. **Cooldown (REOPEN_COOLDOWN_HOURS=24):**
   - TP/SL/trailing ile kapanan bet → 24 saat re-entry engeli
   - Settled bet (won/lost) → 24 saat re-entry engeli
   - Rolling 24h penceresi (calendar-day değil)

3. **City+Threshold Dedup (place_all_pending içinde):**
   - Aynı şehir + aynı metric + aynı threshold + aynı tarih → engelle

### Senaryo: Ankara Yarın 25°C

| Durum | Açılır mı? |
|-------|-----------|
| Aktif bet var | ❌ HAYIR |
| TP ile kapandı, 1 saat sonra | ❌ HAYIR (cooldown) |
| TP ile kapandı, 25 saat sonra | ✅ EVET |
| `REOPEN_COOLDOWN_HOURS=8760` | ❌ 1 yıl boyunca açılmaz |

## 16. Portföy Muhasebesi

**Kaynak kod:** `utils/formulas.py` (tek kaynak), `utils/accounting.py`

| Formül | Açıklama |
|--------|----------|
| `max_bet_cap(portfolio, pct)` | Per-bet cap |
| `conservative_portfolio_value(initial, realized)` | Feedback loop önleme (unrealized hariç) |
| `max_exposure_cap(initial, realized, pct)` | Toplam exposure limiti |
| `unrealized_pnl(shares, current, entry)` | Açık pozisyon PnL |
| `settlement_pnl(stake, entry, fee, won)` | Settled PnL |
| `polymarket_fee(shares, price, rate)` | Resmi: `C × feeRate × p × (1-p)` |
| `portfolio_total_value(cash, exposure)` | Book value |
| `portfolio_current_value(initial, realized, unrealized)` | Market value |
| `debit_stake(session, amount, reason)` | Nakit düş (bet açılışı) |
| `credit_sale(session, amount, reason)` | Nakit ekle (settlement) |

### Portföy Durumu (örnek)

```
Başlangıç:  $1,000.00
Realized:   +$400.00
Unrealized: +$69.18
Toplam:     $1,469.18
Exposure:   $176.79 (max $250)
Açık bet:   11 adet
Win Rate:   %49.4
ROI:        %10.1
```

## 17. Test Çalıştırma

```bash
# Tüm testler (330 test, 43 dosya)
PYTHONPATH=. pytest

# Sadece belirli test
PYTHONPATH=. pytest tests/test_calculator.py -v

# Lint
ruff check .

# Type check
mypy . --ignore-missing-imports

# Coverage
coverage run -m pytest
coverage report

# Full pipeline
ruff check . && mypy . --ignore-missing-imports && PYTHONPATH=. pytest -q --tb=short
```

## 18. Sık Sorulan Sorular

### Bot live trade yapıyor mu?

Hayır. `DRY_RUN=true` (varsayılan) ile paper mode'da çalışır. Live trade için:
1. `DRY_RUN=false` set et
2. Polymarket cüzdanı bağla (private key)
3. `LIVE_TRADING_ENABLED=true` set et

### Portföy neden $1,000'den başlıyor?

`INITIAL_PORTFOLIO=1000.0` varsayılan değerdir. İstediğiniz miktarı `.env`'de değiştirebilirsiniz.

### Bot neden bet açmıyor?

Sağlık kontrolü yapın: `GET /api/health-check`. Olası sebepler:
- "Az kaynak: 0" → Open-Meteo o şehir/tarih için veri dönmedi (normal)
- "edge_positive" → Edge min_edge ( %30) altında
- "exposure_cap" → Exposure limiti doldu
- "daily_loss_limit" → Günlük kayıp limiti aşıldı
- "depth_ok" → Orderbook derinliği yetersiz

### SIA Loop neden çalışmıyor?

SIA saatlik çalışır. Bot'un çalıştığından emin olun (`/api/status` → `is_running: true`). İlk çalışma için yeterli sayıda kapanmış bet gerekir (min 10).

### LLM key'im yok, bot çalışır mı?

Evet. Tüm LLM katmanları (Karpathy, ASI-Evolve, SIA) API key olmadan **deterministic mutation ladder**'a fallback yapar. Bot LLM olmadan da tam işlevseldir.

---
*Son güncelleme: 2026-07-06*
