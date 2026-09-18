"""Deploy gate: restart.bat bunu calistirir, BASARISIZSA eski bot OLDURULMEZ.

Yakalanan bug siniflari (hepsi canlida goruldu):
- IndentationError/SyntaxError (strategy.py vakasi)
- ruff hatalari (undefined name vb.)
- kritik import patlamalari (api, main, calculator, strategy)
"""

import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
fails: list = []


def step(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# 1. Tum .py dosyalari derlenebilmeli (syntax/indent guard)
bad = []
for p in sorted(ROOT.rglob("*.py")):
    if ".venv" in p.parts or "__pycache__" in p.parts:
        continue
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        bad.append(f"{p.relative_to(ROOT)}: {e}")
step("py_compile(all)", not bad, "; ".join(bad[:3]))

# 2. Ruff (hizli, sadece degisen kritik dosyalar + tam kosu kisa)
try:
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "api.py",
            "main.py",
            "bot_loop.py",
            "engine/",
            "executor/",
            "utils/",
            "data_pipeline/",
            "config/",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
    )
    step("ruff", r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-500:])
except Exception as e:
    step("ruff", False, str(e))

# 3. Kritik import smoke (baslangic crash guard)
try:
    import api  # noqa: F401
    import engine.calculator  # noqa: F401
    import engine.strategy  # noqa: F401
    import executor.bet_placer  # noqa: F401

    step("imports", True)
except Exception as e:
    step("imports", False, str(e)[:300])

print("PREFLIGHT:", "OK" if not fails else f"FAILED ({len(fails)})")
sys.exit(1 if fails else 0)
