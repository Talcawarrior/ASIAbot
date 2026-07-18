"""ASIAbot Bot Watchdog - Bot'u izler, çökerse yeniden başlatır.

Bu script bağımsız çalışır ve bot'u izler.
Bot 2 dakika yanıt vermezse otomatik olarak yeniden başlatır.

Kullanım:
    python watchdog.py              # İzleme modu (sonsuz döngü)
    python watchdog.py --check      # Sadece kontrol et
"""

import subprocess
import time
import sys
import os
import platform
import socket
from datetime import datetime

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_URL = "http://127.0.0.1:8091"
CHECK_INTERVAL = 30  # saniye
TIMEOUT = 180  # 3 dakika yanıt yoksa restart

IS_WINDOWS = platform.system() == "Windows"


def log(msg: str):
    """Log yaz."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def is_bot_running() -> bool:
    """Bot çalışıyor mu? Port kontrolü."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result =         sock.connect_ex(('127.0.0.1', 8091))
        sock.close()
        return result == 0
    except Exception:
        return False


def start_bot():
    """Bot'u başlat."""
    cmd = [sys.executable, "main.py", "bot"]
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
    log(f"Bot started (PID: {proc.pid})")
    return proc


def stop_bot():
    """Bot'u durdur."""
    if IS_WINDOWS:
        # Sadece bu bot'un PID'ini öldür, tüm python process'lerini değil!
        import subprocess as _subprocess
        import os as _os
        try:
            netstat = _subprocess.check_output(["netstat", "-ano"], text=True, stderr=_subprocess.DEVNULL)
            bot_pids = set()
            for line in netstat.splitlines():
                if ":8091" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            bot_pids.add(int(parts[-1]))
                        except ValueError:
                            pass
            my_pid = _os.getpid()
            bot_pids.discard(my_pid)
            for pid in bot_pids:
                _subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=_subprocess.CREATE_NO_WINDOW)
        except Exception:
            _subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True, creationflags=_subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.run(["pkill", "-f", "main.py bot"], capture_output=True)
    log("Bot stopped")


def watchdog_loop():
    """Watchdog ana döngüsü."""
    log("=== ASIAbot Watchdog Started ===")

    last_response = time.time()

    while True:
        try:
            # Bot çalışıyor mu?
            if is_bot_running():
                last_response = time.time()
                # Bot health check (HTTP)
                try:
                    import urllib.request
                    req = urllib.request.urlopen(f"{BOT_URL}/api/status", timeout=5)
                    if req.status == 200:
                        log("Bot OK")
                    else:
                        log(f"Bot unhealthy (status={req.status})")
                except Exception:
                    log("Bot port open but API unreachable")
            else:
                # Bot çalışmıyor
                elapsed = time.time() - last_response
                if elapsed > TIMEOUT:
                    log(f"Bot DOWN for {int(elapsed)}s - restarting...")
                    stop_bot()
                    time.sleep(3)
                    start_bot()
                    last_response = time.time()
                else:
                    log(f"Bot not responding ({int(elapsed)}s since last ok)")

        except KeyboardInterrupt:
            log("Watchdog interrupted")
            break
        except Exception as e:
            log(f"Watchdog error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    watchdog_loop()
