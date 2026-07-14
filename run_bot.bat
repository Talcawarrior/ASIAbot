@echo off
cd /d "C:\Users\fdemir\Documents\New project\ASIAbot"
set PYTHONPATH=%CD%

:restart
echo [%date% %time%] ASIAbot starting on port 8091...

REM Clean stale WAL/SHM files if they're old
forfiles /p "data" /m "*.db-wal" /d -0 /c "cmd /c del @path" 2>nul
forfiles /p "data" /m "*.db-shm" /d -0 /c "cmd /c del @path" 2>nul

REM Kill any existing python process on port 8091
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8091" ^| findstr "LISTENING"') do taskkill /F /PID %%a 2>nul

REM Start the bot
python main.py bot
if errorlevel 1 (
    echo [%date% %time%] Bot crashed with error code %errorlevel%
    echo Restarting in 5 seconds...
    timeout /t 5 /nobreak >nul
    goto restart
) else (
    echo [%date% %time%] Bot exited normally
)
