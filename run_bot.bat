@echo off
cd /d "C:\Users\fdemir\Documents\New project\ASIAbot"
set PYTHONPATH=%CD%
echo ASIAbot starting on port 8091...
python main.py bot
if errorlevel 1 (
    echo Bot crashed with error code %errorlevel%
    pause
)
