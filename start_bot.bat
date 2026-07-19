@echo off
REM ================================================
REM asiabot BOT + WATCHDOG
REM Bot'u baÅŸlatÄ±r, Ã§Ã¶kerse otomatik yeniden baÅŸlatÄ±r.
REM ================================================

cd /d "C:\Users\fdemir\Documents\New project\asiabot"

REM Watchdog'u baÅŸlat (arka planda)
echo Watchdog baslatiliyor...
start /B python watchdog.py

REM Ana dÃ¶ngÃ¼ - bot'u baÅŸlat ve izle
:START
echo [%date% %time%] Bot baslatiliyor...
python main.py bot
echo [%date% %time%] Bot durdu! 3 saniye sonra yeniden baslatilacak...
timeout /t 3 /nobreak >nul
goto START

