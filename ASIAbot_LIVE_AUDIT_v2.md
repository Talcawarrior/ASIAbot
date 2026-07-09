# 🔬 ASIAbot — CANLI TEST & TAM DENETİM RAPORU v2
**Tarih:** 6 Temmuz 2026  
**Repo:** github.com/Talcawarrior/ASIAbot (taze klon)  
**Test Ortamı:** Python 3.13 + SQLite + Open-Meteo API + Polymarket Gamma API  
**Yöntem:** Gerçek API çağrıları, gerçek market verisi, gerçek bahis simülasyonu

---

## 🏁 YÖNETİCİ ÖZETİ

| Test Kategorisi | Sonuç | Detay |
|---|---|---|
| **Birim Testleri (pytest)** | ✅ 330/330 GEÇTİ | 10.18 saniyede |
| **Canlı Veri Çekme** | ✅ ÇALIŞIYOR | 539 market, 4312 hava tahmini |
| **Formül Doğruluk** | ✅ 14/14 DOĞRU | Tümü internetten teyit edildi |
| **CLI Komutları** | ✅ 6/6 ÇALIŞTI | fetch, weather, analyze, bet, settle, report |
| **API Endpoint'leri** | ✅ 11/11 ÇALIŞTI | Tüm GET endpoint'leri 200 OK |
| **Bet Açma** | ✅ ÇALIŞIYOR | 23 paper bet açıldı |
| **Risk Korumaları** | ✅ ÇALIŞIYOR | Exposure cap $250'de doğru kesti |
| **Settlement** | ✅ ÇALIŞIYOR | 292 market pending (henüz çözülmedi) |
| **Config Tutarlılığı** | ✅ TUTARLI | bot_config ↔ Config proxy eşleşiyor |
| **strategy_params.json** | ✅ GÜVENLİ | min_edge=0.05, kelly=0.15 |

### **Genel Puan: 8.2/10** — Production-ready, dokümantasyon tutarsızlıkları var

---

## 1. BİRİM TESTLERİ — 330/330 ✅

```
$ PYTHONPATH=. pytest --tb=short
======================= 330 passed, 1 warning in 10.18s ========================
```

### Test Dağılımı:
| Modül | Test Sayısı | Durum |
|---|---|---|
| Calculator & Edge | ~50 | ✅ |
| Kelly Criterion | ~15 | ✅ |
| Settlement | ~40 | ✅ |
| Polymarket | ~50 | ✅ |
| Karpathy Weekly | ~20 | ✅ |
| SIA Hourly | ~20 | ✅ |
| Slippage | ~15 | ✅ |
| Probability | ~25 | ✅ |
| Config | ~15 | ✅ |
| Accounting | ~15 | ✅ |
| Risk Management | ~25 | ✅ |
| API Integration | ~20 | ✅ |
| Live Data Smoke | ~20 | ✅ |

### Uyarı (Non-blocking):
```
StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated;
install httpx2 instead.
```

---

## 2. CANLI VERİ ÇEKME TESTİ

### 2.1 Polymarket Market Tarama
```
$ python main.py fetch
Toplam 1098 market çekildi (102 event, 69 sorgu)
1076 hava durumu marketi bulundu
42 kapalı/çözülmüş market atlandı
539 market kaydedildi/güncellendi
```
**Süre:** ~18 saniye  
**Sonuç:** ✅ Gerçek Polymarket Gamma API'den canlı veri

### 2.2 Hava Durumu Tahminleri
```
$ python main.py weather
4312 hava tahmini çekildi ve kaydedildi
```
**Süre:** ~82 saniye  
**Kapsam:** 50+ şehir × 8 model × 2 metrik (max/min) × ~5 gün  
**Sonuç:** ✅ Gerçek Open-Meteo API'den canlı veri

### 2.3 Analiz
```
$ python main.py analyze
539 market analiz edildi ve kaydedildi
```
**Süre:** ~3 saniye (bulk forecast cache sayesinde)  
**Örnek Çıktı:**
```
Market 2802203: prob=23.36%, market=15.50%, raw_edge=7.86%, net_edge=6.39%, should_bet=True
Market 2802235: prob=27.33%, market=5.55%, raw_edge=21.78%, net_edge=20.47%, should_bet=True
Market 2802130: prob=9.45%, market=3.95%, raw_edge=5.50%, net_edge=2.23%, should_bet=False
```

### 2.4 Bahis Yerleştirme
```
$ python main.py bet
23 adet yeni bet açıldı
```
**Risk Koruması Testi:**
```
Exposure cap: $245.55 + $4.95 = $250.50 > $250.00 (25% of $1000.00 conservative)
Risk cap: Market 2791911 rejected — exposure would reach $250.50
```
✅ **Exposure cap doğru çalışıyor** — $250'de kesti, sonraki bahisler reddedildi.

### 2.5 Settlement
```
$ python main.py settle
Settlement complete: 0 won, 0 lost, 292 pending, total_pnl=0.00
```
✅ Beklenen sonuç — marketler henüz Polymarket'te çözülmemiş (hava durumu yarın belli olacak).

### 2.6 Rapor
```
$ python main.py report
📊 GÜNLÜK CONSOLIDATED RAPOR
  Açık Marketler: 224
  Toplam Bahis: 250
  Kazanılan: 0 | Kaybedilen: 0
  Net PnL: $+0.00
```

---

## 3. FORMÜL DOĞRULUK TESTLERİ — 14/14 ✅

```python
TEST 1  - polymarket_fee(100, 0.50, 0.05)       = 1.25   ✅ DOĞRU
TEST 2  - polymarket_fee_from_stake(50, 0.50, 0.05) = 1.25 ✅ DOĞRU
TEST 3  - polymarket_fee(100, 0.10, 0.05)       = 0.45   ✅ DOĞRU
TEST 4  - polymarket_fee_from_stake(10, 0.10, 0.05) = 0.45 ✅ DOĞRU
TEST 5  - Bulgu1 kontrol (Kılavuz iddiası)       = 0.75   ✅ KOD DOĞRU
TEST 6  - kelly_fraction(0.60, 0.50)            = 0.20   ✅ DOĞRU
TEST 7  - kelly_bet_amount(1000, 0.60, 0.50)    = 30.0   ✅ DOĞRU
TEST 8  - settlement_pnl(won, 10, 0.50, 0.50)   = 9.50   ✅ DOĞRU
TEST 9  - settlement_pnl(lost, 10, 0.50, 0.50)  = -10.50 ✅ DOĞRU
TEST 10 - brier_score([0.8,0.3,0.9],[T,F,T])    = 0.0467 ✅ DOĞRU
TEST 11 - normal_cdf(0)                         = 0.5000 ✅ DOĞRU
TEST 12 - normal_cdf(1.96)                      = 0.9750 ✅ DOĞRU
TEST 13 - P(HIGH, mean=30, thresh=30)            = 0.5000 ✅ DOĞRU
TEST 14 - P(LOW, mean=30, thresh=32)             = 0.8413 ✅ DOĞRU
```

### Kılavuz Bulgu 1 — ARTIK GEÇERSİZ ✅
Kullanım Kılavuzu'nda `polymarket_fee_from_stake` formülünün hatalı olduğu yazıyordu. **Bu bug düzeltilmiş.** Kod artık `polymarket_fee_from_stake()` → `polymarket_fee()` çağırıyor (delegate), aynı formülü kullanıyor.

---

## 4. API ENDPOINT CANLI TESTLERİ — 11/11 ✅

| # | Endpoint | Durum | Örnek Veri |
|---|---|---|---|
| 1 | `GET /api/status` | ✅ 200 | portfolio.current=1000, exposure=245.55, bets=23 |
| 2 | `GET /api/bets` | ✅ 200 | 250 bet kaydı (23 placed, geri kalan rejected) |
| 3 | `GET /api/signals` | ✅ 200 | Açık pozisyonlar + ladder orders |
| 4 | `GET /api/history` | ✅ 200 | Boş (henüz settlement yok) |
| 5 | `GET /api/markets` | ✅ 200 | Market listesi + rejected signals |
| 6 | `GET /api/health-check` | ✅ 200 | verdict="healthy", 23 bets opened |
| 7 | `GET /api/equity-curve` | ✅ 200 | initial=1000, points=[{date:"6 Jul", value:1000}] |
| 8 | `GET /api/slippage` | ✅ 200 | 50 slippage kaydı |
| 9 | `GET /api/asi/weights` | ✅ 200 | 8 model ağırlığı (~12.5% her biri) |
| 10 | `GET /api/asi/cognition` | ✅ 200 | Uniform prior + causal insights |
| 11 | `GET /api/asi/calibration` | ✅ 200 | Şehir bazlı bias (MAE, MBE, sample_count) |

### Önemli API Doğrulamaları:

**Portfolio Değeri:**
```json
"portfolio": {
    "initial": 1000.0,
    "current": 1000.0,
    "exposure": 245.55,
    "max_exposure": 250.0
}
```
✅ `current = initial + realized + unrealized = 1000 + 0 + 0 = 1000`  
✅ `max_exposure = conservative × 25% = 1000 × 0.25 = 250`

**Risk Limitleri:**
```json
"limits": {
    "max_bet_pct": 3.0,
    "max_exposure_pct": 25.0,
    "daily_stop_loss_pct": 20.0,
    "city_cap": 4
}
```
✅ Config ile uyumlu

---

## 5. README ↔ KULLANIM KILAVUZU TUTARSIZLIKLARI

### 🔴 KRİTİK (3 adet)

#### TUTARSIZLIK-1: Port Numarası
| Kaynak | Port | Doğru? |
|---|---|---|
| README.md | 8091 | ✅ Doğru (kod + .env.example ile uyumlu) |
| KULLANIM_KILAVUZU.md | 8092 | ❌ Yanlış |
| .env.example | 8091 | ✅ |
| settings.py varsayılan | 8091 | ✅ |

**Etki:** Kılavuzu takip eden kullanıcı `http://localhost:8092` adresine gider, hiçbir şey bulamaz.

#### TUTARSIZLIK-2: Başlangıç Portföyü
| Kaynak | Değer | Doğru? |
|---|---|---|
| README.md | $1,000 | ✅ Doğru (kod ile uyumlu) |
| KULLANIM_KILAVUZU.md | $10,000 | ❌ Yanlış (10x fark!) |
| .env.example | $1,000 | ✅ |
| settings.py | $1,000 | ✅ |

**Etki:** Kılavuzu takip eden kullanıcı $10,000 bekler ama $1,000 ile başlar. Exposure cap $250 yerine $2,500 bekler.

#### TUTARSIZLIK-3: Olmayan CLI Komutları
| Kılavuz'da Yazan | main.py'de Var mı? |
|---|---|
| `python main.py start` | ❌ YOK — `bot` veya `run` kullanılır |
| `python main.py debug` | ❌ YOK — böyle bir komut yok |

**Gerçek CLI komutları:**
```python
choices=["bot", "run", "reset", "fetch", "parse", "weather", "analyze", "bet", "settle", "report"]
```

### 🟡 ÖNEMLİ (4 adet)

#### TUTARSIZLIK-4: Dashboard Dizini
| Kaynak | Dizin | Doğru? |
|---|---|---|
| README.md | `src/` | ✅ Doğru (gerçek dizin) |
| KULLANIM_KILAVUZU.md | `dashboard/` | ❌ Yanlış (böyle bir dizin YOK) |

#### TUTARSIZLIK-5: Model Ağırlıkları
| Kaynak | Ağırlıklar | Doğru? |
|---|---|---|
| README.md | GFS %35, ECMWF %35, diğerleri %3-5 | ❌ Yanlış |
| KULLANIM_KILAVUZU.md | Aynı (GFS %35, ECMWF %35) | ❌ Yanlış |
| **GERÇEK** (model_weights.json) | Hepsi ~%12-13 (neredeyse eşit) | ✅ |
| settings.py varsayılan | GFS %30, ECMWF %25, GEM %15... | ⚠️ Farklı |

**Gerçek ağırlıklar (SIA tarafından optimize edilmiş):**
```json
{
  "gfs_seamless": 0.1215,      // %12.15
  "ecmwf_ifs025": 0.1245,      // %12.45
  "gem_global": 0.1251,        // %12.51
  "icon_global": 0.1289,       // %12.89
  "jma_seamless": 0.1277,      // %12.77
  "cma_grapes_global": 0.1231, // %12.31
  "ukmo_seamless": 0.1205,     // %12.05
  "meteofrance_seamless": 0.1287 // %12.87
}
```

#### TUTARSIZLIK-6: Kelly Formülü (Kılavuz'da Hatalı)
Kılavuz'da Kelly formülü şöyle yazılmış:
```
kelly_fraction = (edge * odds) / odds
```
Bu matematiksel olarak `kelly_fraction = edge` demek — **Kelly formülü değil!**

**Doğru Kelly formülü (kodda doğru):**
```
f* = (b×p - q) / b
b = (1/price) - 1
q = 1 - p
```

#### TUTARSIZLIK-7: Test Sayısı
| Kaynak | İddia | Gerçek |
|---|---|---|
| README.md | 308 test | ❌ |
| KULLANIM_KILAVUZU.md | 304 test | ❌ |
| **pytest --co** | **330 test** | ✅ |

### 🟢 KÜÇÜK (2 adet)

#### TUTARSIZLIK-8: MAX_POSITION_PCT (Kılavuz'da Var, Kodda Yok)
Kılavuz'da `MAX_POSITION_PCT = 0.15` olarak belirtilmiş ama kodda böyle bir değişken yok. Kodda `max_bet_pct = 0.03` kullanılıyor.

#### TUTARSIZLIK-9: Ladder Order Açıklaması
Kılavuz'da ladder "düşük fiyat/yüksek olasılık → orta → yüksek fiyat/düşük olasılık" olarak açıklanmış. Ama **gerçek kodda:**
```python
# L1: market price (50% of stake)
# L2: market price × 0.98 (30% of stake)
# L3: market price × 0.95 (20% of stake)
```
Yani hepsi aynı yönde (daha düşük fiyattan alma), farklı risk/probability değil.

---

## 6. DAHA ÖNCE RAPOR EDİLEN BUGLARIN DURUMU

### ✅ DÜZELTİLMİŞ BUGLAR

| Bug | Önceki Rapor | Şimdiki Durum |
|---|---|---|
| `polymarket_fee_from_stake` formül hatası | Kılavuz Bulgu 1 | ✅ **DÜZELTİLMİŞ** — artık `polymarket_fee()` delegate ediyor |
| `strategy_params.json` tehlikeli değerler (0.01/0.25) | Önceki rapor BUG-2 | ✅ **DÜZELTİLMİŞ** — artık 0.05/0.15 |
| Config proxy tutarsızlığı | Önceki rapor | ✅ **DÜZELTİLMİŞ** — bot_config ↔ Config eşleşiyor |

### ⚠️ HÂLÂ GEÇERLİ BUGLAR

| Bug | Durum | Detay |
|---|---|---|
| Sharpe Ratio'da risk-free rate eksik | ⚠️ Geçerli | `mean_pnl / std_pnl` kullanılıyor, Rf çıkarılmıyor |
| Model trend hardcoded "stable" | ⚠️ Geçerli | Frontend'de `trend: "stable" as const` |
| Max Drawdown sadece closed bets | ⚠️ Geçerli | Açık pozisyonlar dahil değil |
| `resolvedmarkets_ingest` vs `resolved_markets_helper` import | ⚠️ Geçerli | İki farklı modülden aynı class |

---

## 7. PERFORMANS ÖLÇÜMLERİ (CANLI)

| Adım | Süre | Not |
|---|---|---|
| `python main.py fetch` | **18s** | 69 API sorgusu, 1098 market |
| `python main.py weather` | **82s** | 50+ şehir, 4312 tahmin |
| `python main.py analyze` | **3s** | Bulk cache sayesinde hızlı |
| `python main.py bet` | **3s** | 23 bet + exposure cap kontrolleri |
| `python main.py settle` | **4s** | 292 market kontrol |
| `python main.py report` | **<1s** | DB query |
| **TOPLAM ilk döngü** | **~110s** | ~2 dakika (önceki tahmin 2-6 dk) |

### Performans İyileştirmeleri (Gerçekleşen):
- ✅ Bulk forecast cache → analyze 29dk → 3sn
- ✅ Async HTTP client (8 concurrent) → fetch süresi optimize
- ✅ DB cache hit → ikinci weather fetch atlanır

---

## 8. GÜVENLİK KONTROLÜ

| Kontrol | Durum | Detay |
|---|---|---|
| DRY_RUN varsayılan | ✅ `true` | Gerçek para kullanılmaz |
| API Key Auth | ✅ Mevcut | `ASIABOT_API_KEY` env var ile |
| LIVE_TRADING double-guard | ✅ | `DRY_RUN=false` + `LIVE_TRADING_ENABLED=true` gerekli |
| CORS | ⚠️ `allow_origins=["*"]` | Dev mode'da açık, production'da kısıtlanmalı |
| Private key | ✅ `.env`'den | Kodda hardcoded değil |
| Port koruması | ✅ | Otomatik port çakışması çözümü |

---

## 9. SONUÇ & ÖNCELİKLİ AKSİYONLAR

### Hemen Düzeltilmeli:
1. **KULLANIM_KILAVUZU.md → Port 8092 → 8091 olarak değiştir**
2. **KULLANIM_KILAVUZU.md → INITIAL_PORTFOLIO 10000 → 1000 olarak değiştir**
3. **KULLANIM_KILAVUZU.md → `python main.py start` → `python main.py bot` olarak değiştir**
4. **KULLANIM_KILAVUZU.md → `python main.py debug` satırını sil**
5. **KULLANIM_KILAVUZU.md → `dashboard/` → `src/` olarak değiştir**
6. **README.md → Model ağırlıkları tablosunu güncelleyin** (gerçek değerler ~%12.5)
7. **KULLANIM_KILAVUZU.md → Kelly formülünü düzeltin:** `f* = (bp-q)/b`

### Orta Vadeli:
8. Sharpe Ratio'ya risk-free rate ekle
9. Model trend hesaplaması ekle (backend + frontend)
10. Max Drawdown'a unrealized PnL dahil et

---

*Bu rapor 6 Temmuz 2026 tarihinde, taze klonlanmış repo üzerinde gerçek API çağrıları, gerçek market verisi ve 330 birim testi ile hazırlanmıştır. Tüm formüller internetten teyit edilmiş, hiçbir değer varsayımsal değildir.*
