@echo off
cd /d "C:\Users\fdemir\Documents\New project\ASIAbot"
set PYTHONPATH=%CD%
set SKIP_DASHBOARD_BUILD=true

:restart
echo [%date% %time%] ASIAbot starting on port 8091...

REM Sadece port 8091'deki process'i oldur (diger python'lara dokunma)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8091" ^| findstr "LISTENING"') do (
    echo [INFO] Killing stale PID %%a on port 8091...
    taskkill /F /PID %%a 2>nul
)
ping 127.0.0.1 -n 2 >nul

REM WAL/SHM temizligi
del /f /q "data\bot.db-wal" 2>nul
del /f /q "data\bot.db-shm" 2>nul

REM Botu baslat (foreground — crash olursa goto restart ile yeniden baslar)
echo [%date% %time%] Starting python main.py bot...
python main.py bot
set EXITCODE=%errorlevel%

REM Bot cikti — yeniden baslat
echo [%date% %time%] Bot exited (code %EXITCODE%). Restarting in 5s...
ping 127.0.0.1 -n 6 >nul
goto restart
