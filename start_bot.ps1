# ASIAbot Starter Script
# Bot zaten calisiyorsa ve saglikliysa dokunmaz.
# Calismiyorsa temiz bir sekilde baslatir.

$ErrorActionPreference = "SilentlyContinue"
$BOT_DIR = "C:\Users\fdemir\Documents\New project\ASIAbot"
$PORT = 8091
$HEALTH_URL = "http://127.0.0.1:$PORT/api/health-check"

Set-Location $BOT_DIR

# 1. Bot zaten calisiyor mu? Health check yap
try {
    $response = Invoke-WebRequest -Uri $HEALTH_URL -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Write-Host "[OK] Bot is already running and healthy on port $PORT"
        exit 0
    }
} catch {
    Write-Host "[INFO] Bot not responding on port $PORT"
}

# 2. Port 8091'i megal olcekli temizle
Write-Host "[INFO] Cleaning port $PORT..."
$connections = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    $pid = $conn.OwningProcess
    if ($pid -gt 0 -and $pid -ne $PID) {
        Write-Host "[INFO] Killing process $pid on port $PORT"
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

# 3. WAL/SHM temizligi
Remove-Item "$BOT_DIR\data\bot.db-wal" -Force -ErrorAction SilentlyContinue
Remove-Item "$BOT_DIR\data\bot.db-shm" -Force -ErrorAction SilentlyContinue

# 4. Botu baslat
Write-Host "[INFO] Starting bot..."
$env:PYTHONPATH = $BOT_DIR
$env:SKIP_DASHBOARD_BUILD = "true"
Start-Process -FilePath "python" -ArgumentList "main.py bot" -WorkingDirectory $BOT_DIR -WindowStyle Hidden -RedirectStandardOutput "$BOT_DIR\logs\stdout.log" -RedirectStandardError "$BOT_DIR\logs\stderr.log"

# 5. Baslamasini bekle
Write-Host "[INFO] Waiting for bot to start..."
$timeout = 90
$elapsed = 0
while ($elapsed -lt $timeout) {
    Start-Sleep -Seconds 3
    $elapsed += 3
    try {
        $response = Invoke-WebRequest -Uri $HEALTH_URL -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            Write-Host "[OK] Bot started successfully on port $PORT (took ${elapsed}s)"
            exit 0
        }
    } catch {
        Write-Host "[WAIT] ... $elapsed / ${timeout}s"
    }
}

Write-Host "[ERROR] Bot failed to start within ${timeout}s. Check logs\bot.log"
exit 1
