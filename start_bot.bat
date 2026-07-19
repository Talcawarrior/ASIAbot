@echo off
REM ================================================
REM asiabot BOT - TEK YONETICI (watchdog)
REM watchdog.py bot'u baslatir, izler ve takilirsa
REM otomatik olarak yeniden baslatir.
REM watchog'u bagimsiz (detached) baslatir ki bu pencere
REM kapansa bile bot yasamaya devam etsin.
REM ================================================

cd /d "C:\Users\fdemir\Documents\New project\ASIAbot"

start "" pythonw.exe watchdog.py
