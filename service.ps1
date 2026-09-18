# asiabot BOT - PowerShell Service (Ä°yileÅŸtirilmiÅŸ)
# Bot'un tam olarak baÅŸlamasÄ±nÄ± bekler

$BotDir = "C:\Users\fdemir\Documents\New project\asiabot"
$LogFile = "$BotDir\logs\service.log"
$MaxRestarts = 1000
$RestartDelay = 600  # 10 dk (StartupWait ile esit) — bot baslamadan supervisor oldurmesin
$StartupWait = 600  # 10 dk SIA+Karpathy+kalibrasyon'un baÅŸlamasÄ± iÃ§in bekleme sÃ¼resi

function Write-Log {
    param($Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    Write-Host $logMessage
    Add-Content -Path $LogFile -Value $logMessage -ErrorAction SilentlyContinue
}

function Start-Bot {
    Write-Log "Starting bot..."
    $proc = Start-Process -FilePath "pythonw" -ArgumentList "main.py bot" `
        -WorkingDirectory $BotDir `
        -RedirectStandardOutput "$BotDir\logs\bot_console.log" `
        -RedirectStandardError "$BotDir\logs\bot_console.err.log" `
        -PassThru
    Write-Log "Bot started (PID: $($proc.Id))"
    return $proc
}

function Test-BotRunning {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8092/api/status" -TimeoutSec 5 -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

# Main loop
Write-Log "=== asiabot Bot Service Started ==="
$restartCount = 0

while ($restartCount -lt $MaxRestarts) {
    $proc = Start-Bot
    
    # Bot'un tam olarak baÅŸlamasÄ± iÃ§in bekle
    Write-Log "Waiting ${StartupWait}s for bot to initialize..."
    Start-Sleep -Seconds $StartupWait
    
    if (Test-BotRunning) {
        Write-Log "Bot is running successfully"
        
        # Monitor loop
        $checkCount = 0
        $failCount = 0
        while ($true) {
            Start-Sleep -Seconds 30
            $checkCount++

            if (-not (Test-BotRunning)) {
                $failCount++
                Write-Log "Bot health check failed ($failCount/3)..."
                if ($failCount -lt 3) { continue }
                Write-Log "Bot down 3 checks in a row! Restarting..."
                break
            }
            $failCount = 0
            
            # Check if process is still alive
            if ($proc.HasExited) {
                Write-Log "Bot process exited! Restarting..."
                break
            }
            
            # Her 10 kontrolde bir log yaz
            if ($checkCount % 10 -eq 0) {
                Write-Log "Bot still running (check #$checkCount)"
            }
        }
    } else {
        Write-Log "Bot failed to start after ${StartupWait}s"
        # Bot'u Ã¶ldÃ¼r ve yeniden dene
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    
    $restartCount++
    Write-Log "Restart attempt $restartCount of $MaxRestarts"
    Start-Sleep -Seconds $RestartDelay
}

Write-Log "=== Service stopped (max restarts reached) ==="