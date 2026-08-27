@echo off
REM Windows arka planda 24 saat calisir - bot ile birlikte otomatik baslar
REM Manuel: scripts\run_forecast_collector.bat
cd /d "%~dp0.."
python -m data_pipeline.t_horizon_collector
python -m data_pipeline.t_horizon_report
pause
