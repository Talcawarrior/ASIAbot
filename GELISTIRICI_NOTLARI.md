# Geliştirici Notları

## Zorunlu Kurallar

### 1. Her kod değişikliğinden sonra testleri çalıştır ve botu başlat

Herhangi bir kod değişikliği (backend, frontend, utils, test, her ne olursa olsun) yapıldığında:

```bash
# 1. Ruff kontrolü (F, E, W kuralları)
ruff check

# 2. Pylint kontrolü
pylint --disable=C,R --score=n api.py bot_loop.py watchdog.py service.py

# 3. Testleri çalıştır
python -m pytest tests/ -x -q --tb=short

# 4. Botu yeniden başlat
python main.py restart
```

Bu adımlar **atlanamaz**. Değişiklik ne kadar küçük olursa olsun, testler çalıştırılmalı ve bot yeniden başlatılmalıdır.

### 2. database/db.py — KESİNLİKLE DOKUNMA

**`database/db.py` dosyasına asla dokunulmayacak.**

Bu dosya:
- Botun gerçek veritabanı bağlantısını yönetir
- Engine, SessionLocal, DB_PATH gibi kritik altyapıyı içerir
- Tüm modüller tarafından import edilir
- En ufak bir değişiklik tüm botu çökertir

Bu dosyada değişiklik yapmak yerine:
- Testler için temp DB kullanılacaksa test dosyasının içinde `importlib.reload(database.db)` yap
- Yeni bir özellik eklenmesi gerekiyorsa ayrı bir modülde yap
- Herhangi bir sorun varsa sadece kullanıcıya bildir, dokunma

### 3. Mevcut kodu yeniden yazma

Sadece hedeflenen değişikliği yap. İlgisiz kodları yeniden yazma, "temizlik" yapma.

### 4. Minimal diff

Mümkün olan en küçük değişiklikle işi çöz. Gereksiz satır ekleme/çıkarma yapma.

### 5. Gerçek DB asla değiştirilmez

- Bot çalışırken asla DB'ye direkt SQL yazma
- Tüm işlemler API/uygulama katmanından yapılır
- Testler temp DB kullanır, gerçek DB'ye dokunmaz

### 6. Her kod değişikliğinden sonra ayrı branch'e push et

Herhangi bir kod değişikliği (backend, frontend, utils, test, config, her ne olursa olsun) yapıldığında:

```bash
# 1. Yeni branch oluştur veya mevcut branch'te çalış
git checkout -b <aciklama>/<kisa-konu>

# 2. Değişiklikleri stage et ve commit yap
git add .
git commit -m "KISA: Yapılan değişikliğin özeti"

# 3. Branch'i push et
git push origin <branch-adi>

# 4. (Opsiyonel) PR oluştur
gh pr create --fill
```

**Kurallar:**
- Asla `main`, `dev` veya `feature/partial-tp` gibi ana branch'lere direkt push yapma
- Her branch sadece TEK bir konuyu/feature'ı/bug fix'ini içermeli
- Branch ismi formatı: `<tip>/<kısa-açıklama>` (örn. `fix/scan-loop-crash`, `feature/new-endpoint`, `test/calculator- coverage`)
- Commit mesajı İngilizce ve açıklayıcı olmalı
- Push etmeden önce testleri çalıştır (Kural 1)

### 7. "Pending" market ne demek?

Bot database'deki `bets` tablosunda `status="open"` olan kayıtlar **pending** olarak adlandırılır. Bunlar:
- Polymarket'te hala işlem gören (açık) marketlerdir
- Henüz kazanç/kayıp olarak sonuçlanmamıştır
- Settlement loop'u her döngüde bu marketleri Polymarket API'den sorgular
- Polymarket marketi çözünce (`resolved=yes/no`), bot ilgili bet'i günceller
- `0 won, 0 lost, N pending` = henüz hiçbiri çözülmemiş, bu NORMALDİR

**Neden çözülmez?** Polymarket marketleri genellikle target_date'den 24-48 saat sonra çözülür. Bot'un görevi sabırla beklemek ve çözülünce işlem yapmaktır.


## 2026-09-13 - Tum kaynaklar kalibrasyon + ensemble icinde
- historical_calibrations canli tabloya backfill: ForecastArchive (6 kaynak) + Heat snapshots/observations (NWS 2021+, VC/WAPI/OWM/OM) + OM arsiv parquet. Canli tablo: 53.056 satir, 17 model. 0.0 failed-fetch satirlari temizlendi (480).
- NOT: auto_cleanup (hot 10 gun) eski satirlari parquet arsive tasir; 48.484 satir data/archive/historical_calibrations_20260913.parquet icinde guvende. Canli tablo hot-window tutar.
- Kopru: bridge_archive_to_forecasts (t_horizon_collector) ForecastArchive satirlarini WeatherForecast tablosuna yazar; bot_loop forecast dongusunden cagrilir. Ilk kosu: 2.956 satir.
- MODEL_WEIGHTS eklendi: weatherapi 0.05, openweather 0.05, weathercom 0.03, pivotal_gfs 0.03, iem_mos 0.03.
- asi_calibration.json recalculate ile yenilendi: 90 -> 57 sehir (hot window), 17 model.
- .env: BOM temizligi + PORT=8092 (Junbo 8091 ile cakisma bitti).
- GOZLEM: 17:37 restart sonrasi 27 stop-loss toplu gerceklesti (-105.38); pozisyonlar zaten derindeydi. Takip edilmeli.


## 2026-09-13 - Kaynak-bazli sehir karalistesi aktif
- data/model_blacklist.json uretildi: son 30 gun MAE>2.5, n>=5, 0.0 failed-fetch satirlar haric. 14 modelde 81 eslesme, 26 sehir.
- Format: sehir ICAO -> [modeller] (calculator get_blacklisted_models ile uyumlu). Ornek: KLAX ecwmf/icon/nws/owm yasak; KDAL sadece nws.
- Bot restart sonrasi logda 276 Blacklist eleme goruldu (ornek LTFM: VC+WAPI cikti, 3 model kaldi).


## 2026-09-13 - Gunluk kalibrasyon + blacklist otomasyonu
- renew_calibration_and_blacklist (t_horizon_collector): her gun 00:30 t_horizon_report sonrasi calisir. Yeni actual eslesmelerini tabloya ekler, blacklisti yeniler, bellek-ici haritalari tazeler (restart gerekmez).
- Ilk kosu: +5.313 satir; blacklist 29 yasak/12 sehir (hot-window, muhafazakar). Dosya formati: ICAO -> [modeller].
- NOT: blacklist dosyasi process basina cachelenir; dosya disaridan degisirse restart gerekir (gunluk job kendi cacheini tazeler).


## 2026-09-13 - Yeni sehir otomasyonu
- resolve_new_cities (t_horizon_collector): detected_new_cities.json -> Open-Meteo geocoding -> 150km icinde ICAO -> harita + no_coords acma + Heat gun-bir bias. Gunluk renew icinde otomatik.
- 22 havalimani dogrulandi (geocoding + Heat istasyonlari), CITY_ICAO_MAP + ICAO_COORDS genisletildi (ZGGG, LIMC, KAUS, ZSQD, RKPK, RKSI, RPLL, WMKK...).
- Nufus filtresi (>=50k) cop eslesmeleri eliyor (Below/Higher red).
- market_parser resolved_cities.json fallback okur; settings acilista dosyayi birlestirir.
- Kapsama disi kalan: Jinan (yakin ICAO/istasyon yok) -> no_coords devam, insan karari gerekir.


## 2026-09-15 - Karar motoru mudahalesi (kayip teshisi)
- Teshis: 125 kapanmis bette kazanan edge %7.2 < kaybeden %10.96 (edge ayirt etmiyor); SL cikislari -27%%..-99%%; 0.00-0.05 giris bandi 45 bette -113.54 (toplam zararin %62si); ensemble spread (0.2-0.9) gozlenen MAE (1.2-1.7) altinda.
- Mudahale: min_entry_price 0.01 -> 0.20 (strategy_params.json; 0.20 bandi tarihselde basa bas); sigma tabani 1.0C (calculator, ensemble + per-model prob); SIA edge 0.15/kelly 0.05 aynen calisiyor.
- Gate backtest: 0.20 -> 18 bet, %16.7 win, -5.15 (onceki -183.08).
- test_faz25_35 2 fail PRE-EXISTING (stash ile dogrulandi).


## 2026-09-16 - Signal-decay cikisi (kodlandi, deploy bekliyor)
- RiskManager.check_signal_decay: model edge -5pp altina dusunce stop gapini beklemeden cik. scheduler baglanti tamam, 42 risk testi yesil, unit dogrulandi.
- CANLIYA ALINAMADI: 8092 holder PID 17416 baska kullanici baglaminda (Access denied). /api/start ile donguler baslatildi (eski kodla calisiyor). Deploy icin admin restart gerekli.


## 2026-09-16 - Bilgi tazeligi kapisi (madde 2, kodlandi testli, deploy admin bekliyor)
- calculator: piyasa fiyati tahminlerden yeniyse esik x1.5 + sebep notu. 47 test yesil.
- Madde 1 (signal-decay) ile birlikte admin restartta canliya cikacak.


## 2026-09-16 - Madde 3+4 kodlandi (deploy admin restart bekliyor)
- Istasyon override: kayitli resolution station sehirden 25km+ uzaktaysa tahminler istasyon koordinatiyla cekilir.
- /api/edge-calibration: giris-edge bucket vs win-rate/PnL; Health sekmesinde Edge Kalibrasyonu tablosu.
- Deploy: 8092 holder PID 17416 baska baglamda (Access denied) - restart.bat yonetici olarak calistirilinca aktif.


## 2026-09-16 - Son durum (kalici)
- Bot (ASIAbot) 8092: calisiyor; tarama taze (scan taze); dashboard (ASIAbot ismi, 4 sekme, Model sekmesi korumali) dogrulandi.
- Bot kalibrasyon/backfill: ForecastArchive -> historical_calibrations + Heat -> canli; 53.056 satir canli, 12 model; blacklist 29 yasak/12 sehir.
- 4 yeni kod duzeltmesi (min_entry 0.20, sigma tabani 1.0, sinyal-bozulma cikisi, tazelik kapisi + station override): kodlendi, derlendi, 47/47 test yesil. Deploy admin restart gerekli (eski bot hala 8092 dinliyor).
- Supervisor (service.ps1 + watchdog + bot_launcher): 8092 tek bot, 600 sn startupWait, mutex tekiligi; restart.bat tek port kill (8091 Junbo dokunmaz).
- Eksik deploy: restart.bat yonetici olarak bir kez calistirilinca 4 yeni degisiklik canli cikacak.


## 2026-09-17 - Test sureci duzeltmesi (neden testler yakalamadi)
- 5 yeni sozlesme testi: tests/test_dashboard_contract.py (fee alanlari, threshold, exit tipi, decay kar-koruma, edge endpoint).
- Deploy kapisi: preflight_check.py (py_compile+rull+import); restart.bat preflight basarisizsa eski botu OLDURMEZ.
- strategy.py IndentationError kok neden: index-tabanli duzenleme; kural: cok-satirli duzenlemede Edit araci + her adimda py_compile.
- Tum ruff hatalari sifirlandi (benim + pre-existing splitler; F401 statistics yanlis alarm, noqa eklendi).


## 2026-09-17 - Olu kod temizligi (veri haric)
- Silinen: _archive/*.py+log+pycache (69 dosya, ~7.261 satir), utils/utils aynasi (16 dosya, 2.382 satir), 34 kullanilmayan shadcn bileseni (~4.448 satir), kok check_*.py x5, tools/fix_avast_ca.py, test_sia.py. quick_test_results.json KORUNDU.
- Veri (tahmin/sonuc/orderbook/parquet/db/log) hicbirine dokunulmadi.
- Dogrulama: import OK, next build OK, weather_sources 22/22, dead-fonksiyon sayisi 57->22 (kalan 22 pre-existing, canli dosyalarda).
