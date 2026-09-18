@echo off
cd /d "%~dp0"

echo [0/3] Preflight kontrolu (syntax+lint+import)... hata varsa ESKI BOT OLDURULMEZ.
python preflight_check.py
if errorlevel 1 (
    echo PREFLIGHT BASARISIZ - eski bot calismaya devam ediyor, deploy iptal.
    pause
    exit /b 1
)
echo Preflight OK.

echo [1/3] 8092 portunu tutan eski bot olduruluyor (8091 Junbo'ya DOKUNULMAZ)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":8092 "') do (
    echo   - olduruluyor PID %%a
    taskkill /f /pid %%a
)
timeout /t 3 /nobreak >nul

echo [2/3] Yeni bot baslatiliyor...
start "" pythonw main.py bot >> logs\stdout.log 2>> logs\stderr.log

echo [3/3] Dogrulama (90 sn bekleniyor)...
timeout /t 180 /nobreak >nul
powershell -NoProfile -Command "try { $d = Invoke-RestMethod 'http://127.0.0.1:8092/api/status' -TimeoutSec 15; Write-Output ('SONUC: running=' + $d.is_running + ' last_scan=' + $d.last_scan) } catch { Write-Output ('SONUC: BASARISIZ - ' + $_.Exception.Message) }"
echo.
echo Pencereyi kapatabilirsin.
pause
