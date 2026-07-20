# ASIAbot — Checkpoint Soruları (oturum: 2026-07-20)

Bu dosya, bu oturumda yapılan işlerin **yeniden sorulup doğrulanabileceği**
checkpoint sorularını içerir. Her checkpoint; soruyu, kabul kriterini (doğru
cevabı) ve nasıl doğrulanacağını (komut / dosya:satır) belirtir.

> Not: Bot şu an **PAPER / DRY_RUN modunda** ve 10 gün daha öyle kalacak.
> Canlı trade için `DRY_RUN=false` + `LIVE_TRADING_ENABLED=true` gerekir.

---

## C1. Git push & 5.7 GB blob temizliği
**Soru:** Push başarılı mı ve tarihten dev blob'lar silindi mi?
**Kabul kriteri:** `origin/fix/bot-stability-and-bet-sizing` = `4f625f8..ee4f72d`
(6 commit → filter-branch ile 5'e indi, `4f625f8` taban dokunulmadı). `.git`
~204 MB, `data/backups` retention=20, `node_modules` hariç.
**Doğrulama:**
```powershell
git log --oneline origin/fix/bot-stability-and-bet-sizing ^4f625f8
git rev-parse HEAD   # ee4f72d olmali
```

## C2. Dashboard Günlük PnL Zaman Çizelgesi (16/7 başlangıç + USD ekseni)
**Soru:** Çizelge en soldan 16/7'den mi başlıyor ve Y ekseni USD mi?
**Kabul kriteri:** `api.py` `daily_pnl_timeline` baştan boş günleri trim'ler
(ilk `total>0` gün = 16/7). `src/app/page.tsx` YAxis: `domain=[0,"auto"]`,
`allowDecimals=false`, `tickFormatter={(v)=>`$${Math.round(v)}`}`, `width=56`.
`next build` ile `out/` yeniden üretilmiş.
**Doğrulama:** tarayıcıda /api/health-check → daily_pnl_timeline ilk öğe 16/7;
sayfada Y ekseni "0, 200, 400 ..." şeklinde.

## C3. Canlı fiyat çekme (run_update_prices)
**Soru:** Açık pozisyonlu piyasaların fiyatı artık Gamma'dan canlı mı çekiliyor?
**Kabul kriteri:** `jobs/scheduler.py` `run_update_prices` açık bet'i olan
piyasalara ait `yes_price`/`no_price`'ı canlı Gamma'dan günceller (eski hali
sadece cache kullanıyordu). `import time` ekli. UI fiyatı canlı ile aynı
(Δ≈0.000).
**Doğrulama:**
```powershell
Select-String -Path jobs/scheduler.py -Pattern "run_update_prices|live|Gamma"
```

## C4. 0.98 otomatik kapatma kuralı
**Soru:** Fiyat 0.98'i geçince otomatik kapanma kuralı var mı ve ateşleniyor mu?
**Kabul kriteri:** `engine/strategy.py` `check_take_profit` içinde
`if current_price >= 0.98: return True` (satır ~308). `jobs/scheduler.py`
`near_certain_win` dalı (satır ~365-412) pozisyonu tam kapatır (`closed_early`).
Kural, canlı fiyat düzeltmesinden ÖNCE bayat cache yüzünden ateşlenmiyordu;
artık ateşleniyor.
**Doğrulama:** `Select-String -Path engine/strategy.py -Pattern "0.98"`
+ `Select-String -Path jobs/scheduler.py -Pattern "near_certain_win"`

## C5. Kapanan bahislerin PnL hesaplaması / paper mod gerçeği
**Soru:** Bütün kapanan bahisler neye göre hesaplandı, kârlar gerçek miydi?
**Kabul kriteri:**
- Bot **PAPER modunda** (`config/settings.py`: `dry_run: bool = True`;
  `LIVE_TRADING_ENABLED` tanımsız → false). Yani gerçek para yok, tüm PnL simülasyon.
- Gamma-çözülen (`won`/`lost`): `settlement_pnl(stake, entry_price, entry_fee, won)`
  → resmi sonuç, gerçekçi.
- Erken kapanan (`closed_early`, 248 adet, ~562 / 578 toplam realized):
  `current_price` (bayat cache) ile hesaplanıyordu → yön doğru, fiyat sapmalı.
- Önemli: erken-çıkış **gerçek Polymarket satışı yapmıyordu** (sadece DB'ye
  kâr yazılıyordu). Bu oturumda `exit_position` eklenerek kapatıldı (C6).
**Doğrulama:**
```powershell
python -c "import os; print('DRY_RUN env:', os.getenv('LIVE_TRADING_ENABLED'))"
```
+ `Select-String -Path config/settings.py -Pattern "dry_run"`
+ `Select-String -Path executor/bet_placer.py -Pattern "_live_allowed"`

## C6. Gerçek `sell` metodu (exit_position) — paper-safe
**Soru:** Erken-çıkış artık Polymarket'te gerçekten satış yapıyor mu (ama paper modda yan etkisiz mi)?
**Kabul kriteri:** `executor/bet_placer.py`'de `exit_position(market, side, price, size, reason)`
metodu var. Canlı modda (`DRY_RUN=false` + `LIVE_TRADING_ENABLED=true`)
`client.create_and_post_order(..., side=SELL)` çağırır; paper modda yalnızca
`paper_sell_*` kaydı döndürür, gerçek emir YOK. `jobs/scheduler.py`
`run_risk_management` hem tam kapanmada hem `_partial_close_early`'da
`placer.exit_position(...)` çağırır ve `bet.tx_hash`'e satış orderID'sini yazar.
**Doğrulama:**
```powershell
Select-String -Path executor/bet_placer.py -Pattern "def exit_position"
Select-String -Path jobs/scheduler.py -Pattern "exit_position"
python -m pytest tests/test_executor_exit.py -q   # 2 passed
```
> 10 gün sonra canlıya geçiş: `DRY_RUN=false` ve `LIVE_TRADING_ENABLED=true`
> ayarla; `polymarket.private_key` mevcut olmalı.

## C7. Yedekleme (db_backup) denetimi
**Soru:** Gerçekten yedek alınıyor mu, nereye, kaç adet, eskiler siliniyor mu, geri kurulabilir mi?
**Kabul kriteri:**
- Yedekler GERÇEK alınıyor: `data/backups` (yerel) + `..\ASIAbot_backups_offsite`
  (offsite, aynı C: diski). Hepsi `integrity_check = ok`.
- Sadece `.db` (`.db.gz`) alınır; `.wal`/`.shm` ayrı alınmaz AMA Online Backup
  API (`src.backup`) WAL içeriğini `.db.gz` içine katıyor → geri yükleme tam.
- Yerel retention: kategori başına 20 (`MAX_BACKUPS_PER_CATEGORY`), sonra en
  eskiler silinir. **Offsite artık aynı kurala tabi** (`_cleanup_offsite` eklendi).
- Yazılan her yedek artık write-anında integrity doğrulanır (uyarı loglanır).
- Testler artık `OFFSITE_DIR`'i mock'luyor → gerçek offsite kirlenmiyor.
- 36 adet test-çöpü (<1 MB, yalnızca `trades` tablolu) offsite'den silindi.
**Doğrulama:**
```powershell
python db_backup.py --list        # hepsi [ok]
python -c "import db_backup, glob; print(len(glob.glob('data/backups/bot_*.db.gz')), 'yerel')"
Select-String -Path db_backup.py -Pattern "_cleanup_offsite|verify_backup\(gz_path\)"
python -m pytest tests/test_backup_restore.py -q   # 7 passed (icinde offsite retention + written integrity)
```
**Geri yükleme testi:** `db_backup.restore_backup(<dosya>)` atomik `os.replace`
yapar; corrupt ise reddeder. (Canlı bot çalışırken yapma — önce durdur.)

## C8. Testlerin neden bulamadığı + eklenen testler
**Soru:** Testler bu açıkları (erken-çıkışta satış yok, offsite retention yok) neden bulamadı, şimdi ne var?
**Kabul kriteri:**
- Neden bulunmadı: (1) `bet_placer.py`'da `sell` metodu hiç yoktu → test
  edemezdi; (2) testler paper modda çalıştığı için satış zaten atlanıyordu;
  (3) offsite retention testi sadece "kopyalandı mı" diye bakıyordu, "eski
  silindi mi" demiyordu; (4) bazı testler `OFFSITE_DIR`'i mock'lamadığı için
  gerçek offsite'i kirletiyordu (C7).
- Eklenenler:
  - `tests/test_executor_exit.py`: `exit_position` paper-safe (paper dict döner)
    + live modda client'ı çağırır (SELL side, doğru size/price).
  - `tests/test_backup_restore.py`: offsite retention truncate + yazılan yedek
    integrity.
**Doğrulama:**
```powershell
python -m pytest tests/test_executor_exit.py tests/test_backup_restore.py -q
python -m pytest -q   # tum paket: 588 passed, 10 skipped
ruff check executor/bet_placer.py jobs/scheduler.py db_backup.py tests/test_backup_restore.py tests/test_executor_exit.py
```

## C9. Genel kalite ağı (önemli)
**Soru:** Kod kalitesi ve çalışan bot durumu nedir?
**Kabul kriteri:** `ruff` temiz; tam test paketi 588 passed / 10 skipped;
canlı bot `is_running=True` (paper). `check.bat` ile tek komutta kontrol.
**Doğrulama:**
```powershell
.\check.bat
```

---

## C10. Bet açma oranı (max_bet_pct) 0.006 → 0.010
**Soru:** Tek bahis büyüklük üst sınırı (portföyün %'si) 0.006'dan 0.010'a çıktı mı?
**Kabul kriteri:** Normal yolda bağlayıcı tavan `max_bet_pct`. İki kaynakta da 0.010:
- `config/settings.py:83` varsayılan `max_bet_pct = 0.010`
- `utils/adaptive_sizing.py:84` `PHASE1_MAX_BET_PCT` varsayılan `0.010`
(0.010 < `MAX_BET_PCT_CEILING = 0.013`. `max_bet_amount=3.0` yalnızca
`calculate_position_size` hata verirse devreye giren fallback — normal yolda bağlamaz.)
**Doğrulama:**
```powershell
python -c "import sys; sys.path.insert(0,'.'); import config.settings as s; print(s.bot_config.strategy.max_bet_pct, s.MAX_BET_PCT_CEILING); import utils.adaptive_sizing as a; print(a.PHASE1_MAX_BET_PCT)"
# beklenen: 0.01 0.013 0.01
```
> Değişiklik import zamanında okunur → **bot yeniden başlatılınca** devreye girer.
> Etki: tek bahis portföyün %1'i (örn. $1000 → $10/bet, önceki $6).

## Açık / izlenecek konular
1. **Offsite aynı C: diski** → gerçek felaket kurtarma değil. Farklı disk
   mümkün olduğunda `OFFSITE_DIR` başka sürücüye alınmalı (D sürücüsü yasak).
2. **10 gün sonra canlı geçiş** → `DRY_RUN=false` + `LIVE_TRADING_ENABLED=true`
   + `polymarket.private_key`; `exit_position` gerçek satış yapacak. Geçiş
   öncesi canlı Polymarket CLOB client bağlantısı ve SELL emir akışı bir kez
   gerçek ortamda smoke test edilmeli.
3. **En yeni yedek ↔ canlı DB farkı** → son yedekten sonraki işlemler yedekte
   yok (RPO açığı). Scheduled yedek günde 1 + her startup'ta; sıklık yeterli
   görülürse değiştirmeyin.
