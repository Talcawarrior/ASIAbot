# Windows Task Scheduler - t0/t1/t2 collector (her 6 saatte bir)
# Kurulum: PowerShell Admin -> .\scripts\forecast_collector_task.ps1
$TaskName = "ASIAbot_ForecastCollector"
$ScriptPath = Join-Path $PSScriptRoot "..\data_pipeline\t_horizon_collector.py"
$Python = "python"
$Action = New-ScheduledTaskAction -Execute $Python -Argument "-m data_pipeline.t_horizon_collector" -WorkingDirectory (Resolve-Path "$PSScriptRoot\..")
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 6) -RepetitionDuration ([TimeSpan]::MaxValue)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force
Write-Host "Task $TaskName kuruldu - her 6 saatte bir t0/t1/t2 toplar (VC/WeatherAPI/OpenWeather/NWS)"

# Gun sonu raporu (00:35 UTC = 03:35 Istanbul)
$ReportTask = "ASIAbot_T_HorizonReport"
$ReportAction = New-ScheduledTaskAction -Execute $Python -Argument "-m data_pipeline.t_horizon_report" -WorkingDirectory (Resolve-Path "$PSScriptRoot\..")
$ReportTrigger = New-ScheduledTaskTrigger -Daily -At 03:35
Register-ScheduledTask -TaskName $ReportTask -Action $ReportAction -Settings $Settings -Principal $Principal -Force
Write-Host "Task $ReportTask kuruldu - her gun 03:35"
