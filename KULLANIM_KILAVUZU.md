# ASIAbot Kullanim Kilavuzu

**Versiyon:** 1.0
**Tarih:** Haziran 2026
**Platform:** Polymarket (Hava Durumu Ticaret Botu)

---

## 1. ASIAbot Nedir?

ASIAbot, Polymarket uzerinde hava durumu piyasalarinda otonom tahmin ve ticaret yapan bir botudur. 8 farkli meteoroloji modelinden (GFS, ECMWF, GEM, ICON, JMA, CMA, UKMO, MeteoFrance) olusan bir ensambl kullanarak hava durumu olaylari icin olasilik hesaplar ve bu olasiliklari Polymarket fiyatlariyla karsilastirarak edge (kenar) bulur.

**Temel Ozellikler:**

- Python 3.12+ backend, FastAPI sunucusu
- Next.js 16 + shadcn/ui dashboard (port 8092)
- 8 model hava durumu ensamble sistemi
- SIA (Strategic Intelligence Agency) otonom karar verme dongusu
- ASI-Evolve genetik algoritma strateji evrimi
- Karpathy Weekly haftalik strateji optimizasyonu
- LLM 3 katmanli karar dongusu
- DRY_RUN=true varsayilan (paper mode — gercek para kullanilmaz)

---

## 2. Proje Yapisi

```
ASIAbot/
  main.py              — CLI giris noktasi, port cozumleme
  api.py               — FastAPI sunucusu, tum API endpoint'leri, WebSocket
  bot_loop.py          — scan_and_bet_loop, settlement_loop, midnight strategy
  config/
    settings.py        — Config/BotConfig/MeteoConfig veri siniflari, tum env vars
    logging_config.py  — RotatingFileHandler, UTF-8 guvenli loglama
  database/
    models.py          — WeatherMarket, WeatherForecast, Analysis, Bet, Portfolio,
                         ModelPerformance, HistoricalCalibration
    db.py              — SQLAlchemy engine, WAL PRAGMA, oturum yonetimi
  engine/
    calculator.py      — Calculator, WeatherEngine (ensamble agirlikli olasilik)
    strategy.py        — RiskManager, BettingEngine, SIALoop, ActiveRiskManagement
    market_parser.py   — MarketParser (polymarket piyasa verisi ayristirma)
  executor/
    bet_placer.py      — BetPlacer, ladder orders, daily_loss_limit kontrolu
    settler.py         — SettlementEngine, Gamma API ile sonuc kontrolu
  scrapers/
    polymarket.py      — PolymarketScraper (Gamma API, 530 satir)
    meteo.py           — MeteoFetcher (Open-Meteo + WeatherAPI, 411 satir)
  asi_engine/
    orchestrator.py    — ASI-Evolve koordinasyonu
    asi_evolve.py      — Genetik algoritma strateji evrimi
    calibration_engine.py — Model kalibrasyonu
    cognition_base.py  — Persistan bilgi depolamasi (Cognition Nodes)
    karpathy_weekly.py — Haftalik strateji optimizasyonu, OOS degerlendirme
    backtest_simulator.py — Backtest motoru
    llm_client.py      — LLM API istemcisi (ZAI API)
    llm_loop_orchestrator.py — LLM 3 katmanli dongu
  utils/
    formulas.py        — Tum finansal formulor (polymarket_fee, kelly, vb.)
    kelly.py           — Kelly kesirli bahis boyutlandirmasi
    probability.py     — Olasilik tahmini (estimate_probability, normal_cdf)
    slippage.py        — Flat/tiered/orderbook slippage modelleri
    weights_store.py   — Agirlik saklama, strategy_params.json okuma/yazma
  data/
    strategy_params.json — Strateji parametreleri (min_edge, kelly_fraction)
    asiabot.db         — SQLite veritabani
    asi_cognition.json — Cognition dugumleri
  jobs/
    scheduler.py       — Zamanlanmis gorevler (fetch, parse, analyze, place, settle)
  dashboard/           — Next.js 16 + shadcn/ui + Recharts
  tests/               — 304 test dosyasi
```

---

## 3. Kurulum

### On Kosullar

| Gereklilik | Surum | Aciklama |
|-----------|-------|----------|
| Python | 3.12+ | Backend icin |
| Node.js | 18+ | Dashboard icin |
| Polymarket Hesabi | — | API key + ozel anahtar gerekli |
| Open-Meteo API | Ucretsiz | Hava durumu verileri icin |
| WeatherAPI | Opsiyonel | Ek hava durumu verisi icin |
| ZAI API Key | — | LLM kararlari icin |

### Kurulum Adimlari

```bash
# 1. Repoyu klonla
git clone <repo-url> && cd ASIAbot

# 2. Python bagimliliklarini yukle
pip install -r requirements.txt

# 3. Dashboard bagimliliklarini yukle
cd dashboard && npm install && cd ..

# 4. Ortam degiskenleri dosyasini olustur
cp .env.example .env
```

`.env` dosyasini duzenle — minimum gerekli degiskenler:

```env
# Polymarket
POLY_API_KEY=your_poly_api_key
PRIVATE_KEY=your_wallet_private_key
POLY_ADDRESS=your_wallet_address

# LLM
ZAI_API_KEY=your_zai_api_key

# Calisma modu (paper mode icin true birak)
DRY_RUN=true

# Port
PORT=8092
```

---

## 4. Yapilandirma

Tum yapilandirma degiskenleri `.env` dosyasinda veya ortam degiskenleri olarak tanimlanir. Asagidaki tabloda varsayilan degerlerle birlikte verilmistir.

### Temel Degiskenler

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| DRY_RUN | true | Paper mode: gercek bahis yapilmaz |
| INITIAL_PORTFOLIO | 10000 | Baslangic portfoy degeri ($) |
| PORT | 8092 | API sunucu portu |
| LOG_LEVEL | INFO | Loglama seviyesi |

### Risk Yonetimi Degiskenleri

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| DAILY_LOSS_LIMIT | 0.20 | Gunluk maksimum zarar orani (%20) |
| MAX_POSITION_PCT | 0.15 | Tek bahiste maksimum pozisyon orani |
| CITY_CAP | 3 | Sehir basina maksimum bahis sayisi |
| MIN_EDGE | 0.05 | Minimum edge esigi (bahis icin gerekli) |
| KELLY_FRACTION | 0.15 | Kelly kesri (bahis boyutlandirma) |
| WEATHER_FEE_RATE | 0.05 | Polymarket hava durumu ucret orani |

### API ve Servis Degiskenleri

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| POLY_API_KEY | — | Polymarket API anahtari |
| PRIVATE_KEY | — | Cuzdan ozel anahtari |
| POLY_ADDRESS | — | Cuzdan adresi |
| ZAI_API_KEY | — | LLM API anahtari |
| LLM_MODEL | stepfun/step-3.5-flash:free | Kullanilacak LLM modeli |
| WEATHERAPI_KEY | — | WeatherAPI anahtari (opsiyonel) |
| ASIABOT_API_KEY | — | API auth anahtari (bos ise devre disi) |

---

## 5. Calistirma

### Dashboard Baslatma

```bash
cd dashboard
npm run dev
# Tarayicida http://localhost:8092 adresine git
```

### Bot Baslatma

```bash
# Yeni bir terminal ac ve calistir:
python main.py start
```

### Diger CLI Komutlari

```bash
# Sadece analiz (bahis yerlestirme olmadan)
python main.py analyze

# Settlement (sonuclari kontrol et, odemeleri al)
python main.py settle

# Debug modu
python main.py debug
```

### Botu Durdurma

```bash
# Terminalde Ctrl+C
# Veya API uzerinden:
curl -X POST http://localhost:8092/api/stop
```

---

## 6. Botun Calisma Akisi

Bot her dongude (scan_and_bet_loop) asagidaki adimlari sirayla uygular:

**Adim 1: Piyasa Tarama**
- `scrapers/polymarket.py` ile Gamma API'dan aktif hava durumu piyalari cekilir
- Sehir, tarih, piyasa türü (HIGH/LOW/RANGE) bilgileri ayristirilir
- Mevcut piyasalar veritabanina kaydedilir

**Adim 2: Hava Durumu Tahmini**
- `scrapers/meteo.py` ile 8 modelden (GFS, ECMWF, GEM, ICON, JMA, CMA, UKMO, MeteoFrance) tahminler toplanir
- Open-Meteo API ucretsiz olarak kullanilir
- WeatherAPI ek veri saglayabilir

**Adim 3: Ensamble Analiz**
- `engine/calculator.py` ile model tahminleri agirlikli olarak birlestirilir
- Agirliklar `asi_engine/` tarafindan dinamik olarak guncellenebilir
- Sonuc: her piyasa icin bir YES olasiligi

**Adim 4: Edge Hesaplama ve Sinyal Uretimi**
- `engine/strategy.py` ile hesaplanan olasilik ile Polymarket fiyati karsilastirilir
- Edge = model_olasiligi - piyasa_fiyati
- Edge > MIN_EDGE ise bahis sinyali uretilir
- `risk_manager` tarafindan risk kontrolu yapilir

**Adim 5: Bahis Yerlestirme**
- `executor/bet_placer.py` ile bahisler yerlestirilir
- Kelly kesri ile bahis boyutlandirilir
- Ladder order: bahis 3 dilimde yerlestirilir (farkli fiyat seviyelerinde)
- Daily loss limit kontrolu: gunluk zarar limiti asilmamis olmali

**Adim 6: Settlement**
- `executor/settler.py` ile piyasa sonuclari kontrol edilir
- Gamma API uzerinden resolved market bilgisi cekilir
- Kazanilan bahisler icin odeme alinir

---

## 7. Risk Yonetimi Sistemi

### Kelly Kesirli Bahis Boyutlandirma

Kelly formulu, uzun vadede portfoy buyumesini maksimize eden optimal bahis boyutunu hesaplar:

```
kelly_fraction = (edge * odds) / odds
bahis_miktari = portfoy * kelly_fraction * kelly_orani
```

`kelly_fraction` parametresi (varsayilan 0.15) Kelly sonucuyla carpilarak risk azaltilir.

### Ladder Orders

Her bahis 3 dilimde yerlestirilir:
- Dilim 1: Dusuk fiyat, yuksek olasilik (guvenli)
- Dilim 2: Orta fiyat, orta olasilik (dengeli)
- Dilim 3: Yuksek fiyat, dusuk olasilik (agresif)

### Gunluk Zarar Limiti

`executor/bet_placer.py:101` ve `engine/strategy.py:110` dosyalarinda kontrol edilir:
- Gunluk toplam zarar `INITIAL_PORTFOLIO * DAILY_LOSS_LIMIT` degerine ulastiginda bot kilitlenir
- Yeni bahis yerlestirilmez
- Ertesi gun sifirlanir

### Diger Korumalar

| Koruma | Dosya | Aciklama |
|--------|-------|----------|
| Fiyat gecerlilik | bet_placer.py | Piyasa fiyati 0.01-0.99 araliginda olmali |
| Sehir limiti | strategy.py | Sehir basina max CITY_CAP bahis |
| Pozisyon limiti | strategy.py | Tek bahiste max MAX_POSITION_PCT |
| Slippage | slippage.py | Flat/tiered/orderbook modelleri |

---

## 8. ASI Motoru

### SIA (Strategic Intelligence Agency)

`engine/strategy.py` icindeki `SIALoop` sinifi, otonom karar verme dongusunu yonetir:
- Piyasa tarama, analiz, bahis, settlement dongusu
- Her dongude risk kontrolu ve karar verme
- `ActiveRiskManagement` ile gercek zamanli risk takibi

### ASI-Evolve

`asi_engine/asi_evolve.py` — Genetik algoritma ile strateji evrimi:
- Hipotez uretimi (parametre mutasyonlari)
- Backtest ile degerlendirme
- OOS (Out-of-Sample) test ile genelleme kontrolu
- En iyi stratejileri `CognitionBase`'e kaydetme

### CognitionBase

`asi_engine/cognition_base.py` — Persistan bilgi depolamasi:
- Her strateji deneyi bir Cognition Node olarak kaydedilir
- Varsayilan: brier_score=0.25 (uniform prior — tum modellere esit agirlik)
- Dosya: `data/asi_cognition.json`

### Karpathy Weekly

`asi_engine/karpathy_weekly.py` — Haftalik strateji optimizasyonu:
- `build_brier_dataset()` ile model performans verisi olusturma
- Cross-validation split'leri ile OOS degerlendirme
- Brier score, Sharpe ratio, ROI, win rate metrikleri
- Hypothesis testing ile strateji guncelleme

### LLM 3 Katmanli Dongu

`asi_engine/llm_loop_orchestrator.py` — 3 katmanli LLM karar dongusu:
- Karar katmani: Bahis yap/yapma
- Analitik katmani: Veri analizi ve yorumlama
- Stratejik katmani: Uzun vadeli planlama
- `llm_client.py` ile ZAI API uzerinden model cagrisi

---

## 9. Dashboard

Next.js 16 + shadcn/ui + Recharts ile gelistirilmis web arayuzu.

### Erisim

```
http://localhost:8092
```

### Bolumler

| Bolum | Icerik |
|-------|--------|
| Ana Sayfa | Piyasa durumu, aktif bahisler, sinyaller |
| ASI Tab | Model agirliklari, cognition dugumleri, evolve durumu |
| Kalibrasyon | Model kalibrasyon metrikleri |
| grafikler | Recharts ile equity egrisi, slippage analizi |
| Ayarlar | Bot durumu kontrolu (start/stop/reset) |

---

## 10. API Endpoint'leri

### GET Endpoint'leri (Auth Gerektirmez)

| Endpoint | Aciklama |
|----------|----------|
| `/` | Dashboard ana sayfa |
| `/api/status` | Bot durumu (calisiyor/durdu) |
| `/api/markets` | Aktif piyasalar + kacirilmis sinyaller |
| `/api/bets` | Tum bahisler |
| `/api/signals` | Uretilen sinyaller |
| `/api/history` | Gecmis islemler |
| `/api/equity-curve` | Equity egrisi verileri |
| `/api/slippage` | Slippage analizi |
| `/api/health-check` | Saglik kontrolu |
| `/api/asi/weights` | Model agirliklari |
| `/api/asi/cognition` | Cognition dugumleri |
| `/api/asi/calibration` | Kalibrasyon durumu |
| `/api/asi/trades` | ASI islemleri |
| `/api/asi/orderbook` | Orderbook verisi |

### POST Endpoint'leri (Auth Gerektirir — ASIABOT_API_KEY)

| Endpoint | Aciklama |
|----------|----------|
| `/api/start` | Botu baslatir |
| `/api/stop` | Botu durdurur |
| `/api/reset` | Botu sifirlar |
| `/api/cleanup` | Eski verileri temizler |
| `/api/asi/evolve` | ASI-Evolve cagrisi (5 round) |
| `/api/asi/backfill` | Backfill islemi |
| `/api/asi/calibration/recalculate` | Kalibrasyonu yeniden hesaplar |

### Ornek Kullanim

```bash
# Bot durumu sorgula
curl http://localhost:8092/api/status

# Botu baslat
curl -X POST http://localhost:8092/api/start \
  -H "X-API-Key: your_api_key"

# ASI-Evolve calistir
curl -X POST http://localhost:8092/api/asi/evolve \
  -H "X-API-Key: your_api_key"
```

---

## 11. Kritik Kod Bulgulari

Asagidaki bulgular, mevcut kod tabaninda tespit edilen onemli sorunlari ozetler. Bunlar eski-yeni karsilastirmasi degil, mevcut durumun degerlendirmesidir.

### Bulgu 1: polymarket_fee_from_stake Hizli Yol Hatali

**Dosya:** `utils/formulas.py`, satir 278

**Mevcut kod:**
```python
fee = stake * fee_rate * (1.0 - price)
```

**Dogru olmasi gereken:**
```python
fee = stake * fee_rate * price * (1.0 - price)
```

**Etki:** `exponent=1` icin fast path, ucreti `price` faktoru kadar yanlis hesaplar. Ornek: $50 stake, $0.50 fiyat, %3 feeRate icin dogru ucret $0.375 olmali ama hali hazirda $0.75 hesaplanir (2x fazla).

**Kullanim yeri:** `executor/bet_placer.py` dosyasinda entry_fee hesaplamasinda kullanilir.

**Not:** `polymarket_fee()` fonksiyonu (satir 251) dogrudur. Sorun sadece `polymarket_fee_from_stake` fast path'indedir.

### Bulgu 2: strategy_params.json Tehlikeli Varsayilan Degerler

**Dosya:** `data/strategy_params.json`

**Mevcut deger:**
```json
{"min_edge": 0.01, "kelly_fraction": 0.25}
```

**Sorunlar:**
- `min_edge=0.01`: Cok dusuk edge esigi. %1 kenarla bile bahis yapar. Bu, dusuk kaliteli sinyallerde gereksiz risk altina girmeye neden olur. Tavsiye: 0.05 veya daha yuksek.
- `kelly_fraction=0.25`: %25 Kelly orani. Agresif bir bahis boyutlandirmasi. Tavsiye: 0.15.

**Not:** Bu dosya `utils/weights_store.py` uzerinden programatik olarak yuklenir. `.env` dosyasindaki `MIN_EDGE` ve `KELLY_FRACTION` degiskenleri bu degerlerin uzerine yazabilir, ancak dosya mevcut degilse bu degerler kullanilir.

### Bulgu 3: API Auth Varsayilan olarak Devre Disi

**Dosya:** `api.py`, satir 52-64

```python
API_KEY = os.getenv("ASIABOT_API_KEY", "")

async def verify_api_key(x_api_key: str = Header(default="")):
    if not API_KEY:
        return  # No key configured — dev mode, allow all
```

**Sorunlar:**
- `ASIABOT_API_KEY` ortam degiskeni ayarlanmazsa, tum POST endpoint'leri (start, stop, reset, asi/*) kimlik dogrulamasi olmadan calisir.
- Tum GET endpoint'lerinde hic auth yok — herkes piyasa verilerini, bahis bilgilerini gorebilir.
- CORS: `allow_origins=["*"]` — herhangi bir kaynaktan istek kabul eder.

**Onem:** Uretim ortaminda `ASIABOT_API_KEY` mutlaka ayarlanmalidir.

### Bulgu 4: Dead autoresearch Endpoint'i

**Durum:** `autoresearch/auto_scientist.py` dosyasi artik mevcut degil. Yerine `asi_engine/karpathy_weekly.py` kullaniliyor.

Eger dashboard veya dis bir servis `/api/asi/autoresearch/run` endpoint'ini cagiriyorsa, 404 hatasi alir. Dashboard kodunda boyle bir cagri olup olmadigi kontrol edilmelidir.

### Bulgu 5: cognition_base Brier Score Heuristik

**Dosya:** `asi_engine/cognition_base.py`, satir 67

**Mevcut deger:** `brier_score=0.25` (uniform prior)

Bu deger, tum hava durumu modellerine esit agirlik veren baslangic noktasidir. Dogrudur ve beklenen davranistir. Ancak yeni cognition dugumleri uretilirken bu prior'un etkisi unutulmamalidir — ilk strateji kararlari bu varsayimla yapilir.

---

## 12. Veritabani

**Tur:** SQLite + WAL mode
**Dosya:** `data/asiabot.db`

### Tablolar

| Tablo | Aciklama |
|-------|----------|
| weather_markets | Polymarket piyasa verileri |
| weather_forecasts | Hava durumu tahminleri |
| analyses | Analiz sonuclari ve bahis onerileri |
| bets | Yapilan bahisler |
| portfolios | Portfoy gecmisi |
| model_performances | Model performans metrikleri |
| historical_calibrations | Gecmis kalibrasyon verileri |

### WAL Mode

SQLite Write-Ahead Logging (WAL) modu etkindir. Bu, ayni anda okuma ve yazma islemlerinin guvenli sekilde yapilmasini saglar.

---

## 13. Loglama

**Tur:** RotatingFileHandler
**Dosya:** `logs/asiabot.log`
**Boyut:** 10MB x 5 dosya (max 50MB)
**Kodlama:** UTF-8
**Seviyeler:** DEBUG, INFO, WARNING, ERROR

Log dosyalari `config/logging_config.py` ile yapilandirilir. Tum moduller `logging.getLogger("ASIAbot")` kullanarak log yazar.

---

## 14. Testler

**Test sayisi:** 304 dosya
**Framework:** pytest

```bash
# Tum testleri calistir
PYTHONPATH=. pytest -q

# Belirli bir test dosyasi
PYTHONPATH=. pytest tests/test_calculator.py

# Coverage ile
PYTHONPATH=. pytest --cov=.
```

---

## 15. Sikca Sorulan Sorular

**DRY_RUN nedir?**
Paper mode. `DRY_RUN=true` iken bot sadece analiz yapar ve sinyal uretir, gercek bahis yerlestirmez. Piyasa kosullarini test etmek icin kullanilir.

**Bot nasil durdurulur?**
Terminalde `Ctrl+C` veya API uzerinden `POST /api/stop`.

**Kelly nedir?**
Optimal bahis boyutu hesaplama formuludur. Uzun vadede portfoy buyumesini maksimize eder. `kelly_fraction` parametresi ile risk azaltilir (ornek: %15 Kelly = Kelly sonucunun %0.15'i).

**Ensamble nedir?**
8 farkli meteoroloji modelinin agirlikli ortalamasi. Her modelin agirligi, gecmis performansina gore belirlenir.

**SIA nedir?**
Strategic Intelligence Agency — botun otonom karar verme dongusu. Piyasa tarama, analiz, bahis ve settlement adimlarini koordine eder.

**ASI-Evolve nedir?**
Genetik algoritma kullanan strateji evrim sistemi. Farkli parametre kombinasyonlarini test ederek en iyi stratejiyi bulur.

**LLM neden kullaniliyor?**
Hava durumu verilerini yorumlamak, piyasa analizi yapmak ve stratejik kararlar almak icin LLM kullanilir. 3 katmanli dongu: karar, analitik, stratejik.

**Port 8092 neden degismiyor?**
Dashboard ve API ayni portu paylasir. `main.py` port caprismasini otomatik olarak cozer.

**Gunluk zarar limiti nasil calisir?**
Gunluk toplam zarar `INITIAL_PORTFOLIO * DAILY_LOSS_LIMIT` degerine ulastiginda bot yeni bahis yapmayi birakir. Ertesi gun sifirlanir.

**Ladder order nedir?**
Bir bahsin 3 farkli fiyat diliminde yerlestirilmesidir. Riski dagitmak ve ortalama giris fiyatini iyilestirmek icin kullanilir.

---

## 16. Hata Ayiklama

### Bot Baslamadi

| Kontrol | Cozum |
|---------|-------|
| `.env` dosyasi mevcut mu? | `cp .env.example .env` ve duzenle |
| Python versiyonu 3.12+ mi? | `python --version` ile kontrol |
| Bagimliliklar yuklu mu? | `pip install -r requirements.txt` |
| Port 8092 baska bir surecte mi? | Task Manager'dan baska sureci durdur veya PORT degiskenini degistir |
| Polymarket API key gecerli mi? | Gamma API'dan test istegi gonder |

### Bahis Yerlestirilmedi

| Kontrol | Cozum |
|---------|-------|
| DRY_RUN true mu? | `DRY_RUN=false` yap (gercek bahis icin) |
| min_edge cok yuksek mi? | `.env`'de `MIN_EDGE=0.05` ayarla |
| Gunluk zarar limiti asildi mi? | Loglari kontrol et, ertesi gunu bekle |
| Piyasa fiyati gecerli mi? | Fiyat 0.01-0.99 araliginda olmali |
| Yeterli bakiye var mi? | Wallet bakiyesini kontrol et |

### Dashboard Acilmiyor

| Kontrol | Cozum |
|---------|-------|
| Node.js yuklu mu? | `node --version` ile kontrol |
| npm install calistirildi mi? | `cd dashboard && npm install` |
| Port 8092 acik mi? | `http://localhost:8092` tarayicida ac |
| Hata mesaji var mi? | Terminaldeki npm ciktilarini kontrol et |

### API Hatalari

| Kontrol | Cozum |
|---------|-------|
| Bot calisiyor mu? | `GET /api/status` ile kontrol |
| Auth gerekli mi? | `ASIABOT_API_KEY` ayarliysa header'da gonder |
| Network baglantisi | Polymarket Gamma API erisimini kontrol et |
| Rate limit | Cok sik istek atma — Gamma API rate limit var |

---

## 17. Gelistirme Rehberi

### Yeni Bir Model Eklemek

1. `scrapers/meteo.py` dosyasinda yeni fetch fonksiyonu ekle
2. `config/settings.py`'da model agirligini tanimla
3. `engine/calculator.py`'da ensamble'a dahil et
4. Test yaz

### Yeni Bir Piyasa Turu Eklemek

1. `engine/market_parser.py`'da yeni parser ekle
2. `engine/strategy.py`'da strateji mantigini guncelle
3. `api.py`'da endpoint guncelle
4. Dashboard'da gorunumu guncelle

### Strateji Parametrelerini Degistirmek

```bash
# .env uzerinden
MIN_EDGE=0.08
KELLY_FRACTION=0.10

# Veya data/strategy_params.json uzerinden
echo '{"min_edge": 0.08, "kelly_fraction": 0.10}' > data/strategy_params.json
```

---

*Bu belge ASIAbot v1.0 icin gecerlidir. Guncel bilgiler icin kod tabanini kontrol edin.*
