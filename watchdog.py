"""asiabot Bot Watchdog - Bot'u izler, cokerse VEYA icten takilirsa yeniden baslatir.

Bu script bagimsiz calisir ve bot'u izler. Sadece "process olmus mu" degil,
"API saglikli mi / bot gercekten calisiyor mu" kontrolu yapar. Bot su durumlarda
otomatik yeniden baslatilir:
  - Port dinlemiyorsa (process takildi / coktu)
  - /api/status 200 donmuyorsa
  - JSON icinde is_running = false ise  (SCAN LOOP DEAD gibi icten takilma)
  - JSON icinde scan_health = "dead" ise

Kullanim:
    python watchdog.py              # Izleme modu (sonsuz dongu)
    python watchdog.py --check      # Sadece bir kez kontrol et
"""

import subprocess
import time
import sys
import os
import platform
import json
import logging
import atexit

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BOT_DIR, "logs", "watchdog.lock")


def _read_lock_pid():
    try:
        with open(LOCK_PATH) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _pid_alive(pid):
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_singleton():
    """Tek watchdog garantiler. Baska bir watchdog zaten calisiyorsa cik."""
    old = _read_lock_pid()
    if old and old != os.getpid() and _pid_alive(old):
        logger.info("Baska bir watchdog zaten calisiyor (PID %s) - cikiliyor", old)
        sys.exit(0)
    try:
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    def _release():
        try:
            if os.path.exists(LOCK_PATH):
                with open(LOCK_PATH) as f:
                    if f.read().strip() == str(os.getpid()):
                        os.remove(LOCK_PATH)
        except Exception:
            pass

    atexit.register(_release)


BOT_URL = "http://127.0.0.1:8091"
HOST = "127.0.0.1"
PORT = 8091
CHECK_INTERVAL = 30  # saniye - saglik kontrolu araligi
UNHEALTHY_TIMEOUT = 120  # saniye - bu sure boyunca sagliksizsa restart
STARTUP_WAIT = 60  # saniye - bot baslatildiktan sonra ilk kontrole kadar bekle
MAX_RESTARTS = 1000  # guvenlik siniri
# Maintenance lock: while this file exists the watchdog will NOT restart the
# bot, so live code edits / restarts during development don't trigger a
# watchdog-driven restart storm. Remove the file (or use --end-maintenance)
# when edits are done.
MAINTENANCE_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".maintenance")


def in_maintenance() -> bool:
    try:
        return os.path.exists(MAINTENANCE_FLAG)
    except OSError:
        return False


IS_WINDOWS = platform.system() == "Windows"

# ── Logging ──────────────────────────────────────────────────────────────
os.makedirs(os.path.join(BOT_DIR, "logs"), exist_ok=True)
_log_path = os.path.join(BOT_DIR, "logs", "watchdog.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - WATCHDOG - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("watchdog")


def log(msg: str):
    logger.info(msg)


# ── Bot process bulma / oldurme ───────────────────────────────────────────
def find_bot_pids():
    """Bu projenin 'main.py bot' calistiran python process'lerinin PID'lerini bulur.

    Onemli: ayni kodu calistiran baska bot'lari (orn. junbo) YANLISLIKLA
    oldurmemek icin, commandline BU projenin mutlak main.py yolunu icermeli.
    junbo'nun commandline'i sadece 'main.py bot' oldugu icin eslesmez.
    """
    pids = []
    bot_main_abs = os.path.join(BOT_DIR, "main.py")
    if not IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", f"{bot_main_abs}.*bot"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
        return pids

    # Windows: commandline icinde BU projenin mutlak main.py yolu gecen PID'ler
    like_pat = f"*{bot_main_abs}*"
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\""
            f" | Where-Object {{ $_.CommandLine -like '{like_pat}' -and $_.CommandLine -like '*bot*' }}"
            " | Select-Object ProcessId | ConvertTo-Json -Compress"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        out = out.strip()
        if not out:
            return pids
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            pid = item.get("ProcessId")
            if isinstance(pid, int):
                pids.append(pid)
    except Exception:
        pass
    return pids


def kill_pid(pid: int):
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, 9)
        log(f"PID {pid} olduruldu")
    except Exception as e:
        log(f"PID {pid} oldurulemedi: {e}")


def kill_port_owner():
    """Port 8091'i tutan process'leri oldurur (icen takili zombileri de kapsar)."""
    if not IS_WINDOWS:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{PORT}"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    kill_pid(int(line))
        except Exception:
            pass
        return

    try:
        raw = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
        pids = set()
        for line in raw.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
        my_pid = os.getpid()
        pids.discard(my_pid)
        for pid in pids:
            kill_pid(pid)
        if pids:
            # Port bosalana kadar bekle
            for _ in range(20):
                time.sleep(0.5)
                check = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
                if not any(f":{PORT}" in line and "LISTENING" in line for line in check.splitlines()):
                    break
    except Exception:
        pass


def kill_stale_bots():
    """Takilmis / cakismis eski bot process'lerini temizler."""
    killed = False
    for pid in find_bot_pids():
        if pid == os.getpid():
            continue
        kill_pid(pid)
        killed = True
    if killed:
        time.sleep(2)
        kill_port_owner()


# ── Saglik kontrolu ────────────────────────────────────────────────────────
def is_bot_healthy():
    """Bot gercekten saglikli mi? (port + API + is_running + scan_health)

    Dondurur: (saglikli_mi, sebep_metni)
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.urlopen(f"{BOT_URL}/api/status", timeout=5)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception:
        # Port kapali / baglanti yok -> bot takilmis veya cokmus
        return False, "API yanit vermiyor (port kapali)"

    if req.status != 200:
        return False, f"HTTP status {req.status}"

    try:
        data = json.loads(req.read().decode("utf-8"))
    except Exception:
        return False, "JSON okunamadi"

    if data.get("is_running") is not True:
        return False, "is_running = false (bot icerden durmus)"

    scan_health = data.get("scan_health")
    if scan_health == "dead":
        return False, "scan_health = dead (SCAN LOOP DEAD)"

    return True, "ok"


# ── Bot baslatma ────────────────────────────────────────────────────────────
def start_bot():
    cmd = [sys.executable, os.path.join(BOT_DIR, "main.py"), "bot"]
    kwargs = {
        "cwd": BOT_DIR,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    log(f"Bot baslatildi (PID: {proc.pid})")
    return proc


def restart_bot(proc):
    log("=== BOT YENIDEN BASLATILIYOR ===")
    # 1) Yonetilen process'i oldur
    if proc is not None:
        try:
            if proc.poll() is None:
                kill_pid(proc.pid)
        except Exception:
            pass
    # 2) Port'u tutan / eski bot process'lerini temizle
    kill_stale_bots()
    time.sleep(2)
    # 3) Yeni baslat
    return start_bot()


# ── Ana dongu ──────────────────────────────────────────────────────────────
def watchdog_loop():
    log("=== asiabot Watchdog Basladi (oto-iyilestirme aktif) ===")

    # Ilk_acilis: eski takili bot'lari temizle
    kill_stale_bots()

    proc = None
    unhealthy_since = None
    restart_count = 0

    while restart_count < MAX_RESTARTS:
        try:
            healthy, reason = is_bot_healthy()

            if healthy:
                unhealthy_since = None
                # Yonetilen process cikmis mi?
                if proc is not None and proc.poll() is not None:
                    log("Bot process'i kendiliginden cikti, yeniden baslatiliyor...")
                    proc = restart_bot(None)
                    restart_count += 1
                    time.sleep(STARTUP_WAIT)
                    continue
                if proc is None:
                    # Saglikli bot var ama biz yonetmiyoruz -> benimse (sadece izle)
                    log("Saglikli bot zaten calisiyor, izleniyor.")
                else:
                    log("Bot SAGLIKLI")
            else:
                if unhealthy_since is None:
                    unhealthy_since = time.time()
                elapsed = int(time.time() - unhealthy_since)
                log(f"Bot SAGLIKSIZ ({reason}) - {elapsed}s dir")

                if in_maintenance():
                    log("MAINTENANCE kilidi aktif -> yeniden baslatma atlandi")
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Yonetilen bot yoksa (ilk acilis / watchdog yeni basladi)
                # 120s beklemeden hemen baslat.
                immediate = proc is None
                if immediate or elapsed >= UNHEALTHY_TIMEOUT:
                    if immediate:
                        log("Yonetilen bot yok -> hemen baslatiliyor")
                    else:
                        log(f"{UNHEALTHY_TIMEOUT}s sagliksiz -> yeniden baslatma karari")
                    proc = restart_bot(proc)
                    restart_count += 1
                    unhealthy_since = None
                    log(f"Yeniden baslatma #{restart_count}")
                    time.sleep(STARTUP_WAIT)
                    continue

        except KeyboardInterrupt:
            log("Watchdog kullanici tarafindan durduruldu")
            break
        except Exception as e:
            log(f"Watchdog hata: {e}")

        time.sleep(CHECK_INTERVAL)

    log("=== Watchdog durdu (max yeniden baslatma sinirina ulasildi) ===")


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok, why = is_bot_healthy()
        print(f"healthy={ok} reason={why}")
        sys.exit(0 if ok else 1)
    if "--maintenance" in sys.argv:
        open(MAINTENANCE_FLAG, "w", encoding="utf-8").close()
        print(f"Maintenance lock ON ({MAINTENANCE_FLAG}). Watchdog will not restart the bot.")
        sys.exit(0)
    if "--end-maintenance" in sys.argv:
        if os.path.exists(MAINTENANCE_FLAG):
            os.remove(MAINTENANCE_FLAG)
        print("Maintenance lock OFF. Watchdog resumes normal restarts.")
        sys.exit(0)
    acquire_singleton()
    watchdog_loop()
