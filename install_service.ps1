# asiabot BOT - Windows Task Scheduler (Oto-iyilestirmeli)
# Bilgisayar acilinca / kullanici giris yapinca bot'u watchdog ile baslatir.
# watchdog.py bot'u izler, takilirsa otomatik yeniden baslatir.

$BotDir = "C:\Users\fdemir\Documents\New project\asiabot"
$TaskName = "asiabotBot"
$User = "$env:USERDOMAIN\$env:USERNAME"

# Eski task'i temizle
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Action: watchdog.py'yi BAGIMSIZ (detached) bir process olarak baslatir.
# `cmd /c start` ile ayristiriyoruz; boylece Task Scheduler'in is (job)
# agaci watchdog'u oldurmez, gorev "Ready" olsa bile watchdog + bot yasar.
# Bot takilirsa watchdog otomatik yeniden baslatir (singleton kilidi sayesinde
# sadece BIR watchdog calisir).
$startArg = "/c start `"`" pythonw.exe watchdog.py"
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument $startArg `
    -WorkingDirectory $BotDir

# Trigger'lar
$TriggerStartup = New-ScheduledTaskTrigger -AtStartup
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$TriggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 365)

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew

# Principal: gecerli kullanici (bot dogrudan calistiginda calistigi gibi)
# RunLevel Limited -> yonetici (UAC) gerektirmez, kullanici oturumunda calisir
$Principal = New-ScheduledTaskPrincipal `
    -UserId $User `
    -LogonType Interactive `
    -RunLevel Limited

# Task'i kaydet
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($TriggerStartup, $TriggerLogon, $TriggerRepeat) `
    -Settings $Settings `
    -Principal $Principal `
    -Description "asiabot Bot - Watchdog ile oto-yeniden-baslat (crash/sleep/icten-takilma)" `
    -Force

Write-Host "============================================"
Write-Host "  asiabot Bot Service kuruldu!"
Write-Host "============================================"
Write-Host ""
Write-Host "Ozellikler:"
Write-Host "  - Bilgisayar acildiginda baslar"
Write-Host "  - Kullanici giris yaptiginda baslar"
Write-Host "  - Her 5 dakikada bir guvenlik kontrolu"
Write-Host "  - Sleep/Wake otomatik baslatma"
Write-Host "  - Crash'te otomatik yeniden baslatma"
Write-Host "  - ICEREN TAKILMA (SCAN LOOP DEAD) algilanir ve bot yeniden baslatilir"
Write-Host "  - API yanit vermezse / port kapalisa otomatik yeniden baslatilir"
Write-Host ""
Write-Host "Kullanici: $User"
