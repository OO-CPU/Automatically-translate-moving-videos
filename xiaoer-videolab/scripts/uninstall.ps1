# Xiaoer VideoLab — Windows uninstaller

$ErrorActionPreference = "Stop"
$TaskName = "XiaoerVideoLab"

Write-Host "=== Xiaoer VideoLab Uninstaller ===" -ForegroundColor Cyan

# Stop daemon processes
Write-Host "`nStopping daemon..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*server.py*" -or $_.CommandLine -like "*xiaoer*"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  ✓ Daemon stopped" -ForegroundColor Green

# Remove scheduled task
Write-Host "`nRemoving Task Scheduler task..." -ForegroundColor Yellow
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  ✓ Task '$TaskName' removed" -ForegroundColor Green
} else {
    Write-Host "  Task not found (already removed)" -ForegroundColor DarkGray
}

# Remove log directory
Write-Host "`nRemoving logs..." -ForegroundColor Yellow
$logDir = Join-Path $env:LOCALAPPDATA "xiaoer-videolab"
if (Test-Path $logDir) {
    Remove-Item $logDir -Recurse -Force
    Write-Host "  ✓ Logs removed: $logDir" -ForegroundColor Green
} else {
    Write-Host "  No log directory found" -ForegroundColor DarkGray
}

Write-Host "`nDone. You can now delete the extension from your browser." -ForegroundColor Green
