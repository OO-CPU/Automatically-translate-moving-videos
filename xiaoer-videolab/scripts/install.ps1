# Xiaoer VideoLab — Windows installer
# Registers the daemon as a Task Scheduler task that runs at login.
#
# Optional env vars (set before running):
#   $env:VIDEOLAB_COOKIES_BROWSER = "chrome"   # for login-gated videos
#   $env:VIDEOLAB_PREFIX = "小耳-"              # filename prefix
#   $env:VIDEOLAB_MAX_HEIGHT = "2160"           # allow 4K
#   $env:VIDEOLAB_DOWNLOADS = "D:\Videos"       # change download dir

$ErrorActionPreference = "Stop"

$TaskName = "XiaoerVideoLab"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Server = Join-Path $ProjectDir "daemon\server.py"

Write-Host "=== Xiaoer VideoLab Installer ===" -ForegroundColor Cyan

# --- Check dependencies ---

Write-Host "`n[1/4] Checking dependencies..." -ForegroundColor Yellow

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  ✗ Python not found. Install: winget install Python.Python.3.11" -ForegroundColor Red
    exit 1
}
$pyVer = python --version 2>&1
Write-Host "  ✓ $pyVer" -ForegroundColor Green

$ytdlp = Get-Command yt-dlp -ErrorAction SilentlyContinue
if (-not $ytdlp) {
    Write-Host "  ✗ yt-dlp not found. Install: winget install yt-dlp.yt-dlp" -ForegroundColor Red
    exit 1
}
$ytdlpVer = yt-dlp --version 2>&1
Write-Host "  ✓ yt-dlp $ytdlpVer" -ForegroundColor Green

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Host "  ⚠ ffmpeg not found (optional but recommended). Install: winget install ffmpeg" -ForegroundColor DarkYellow
} else {
    Write-Host "  ✓ ffmpeg found" -ForegroundColor Green
}

# --- Cookie browser config ---

$cookiesBrowser = $env:VIDEOLAB_COOKIES_BROWSER
if (-not $cookiesBrowser) {
    Write-Host "`n  Bilibili/YouTube often need browser cookies to bypass anti-bot." -ForegroundColor DarkGray
    $input_browser = Read-Host "  Which browser to pull cookies from? (edge/chrome/none) [edge]"
    if (-not $input_browser) { $input_browser = "edge" }
    if ($input_browser -ne "none") { $cookiesBrowser = $input_browser }
}

# --- Unregister old task if exists ---

Write-Host "`n[2/4] Registering Task Scheduler task..." -ForegroundColor Yellow

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  → Removing existing task..." -ForegroundColor DarkGray
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build the action: run python with the server script
$pythonPath = (Get-Command python).Source
$envArgs = ""
if ($cookiesBrowser) {
    $envArgs = "set VIDEOLAB_COOKIES_BROWSER=$cookiesBrowser && "
}
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$envArgs`"`"$pythonPath`" `"$Server`"" -WorkingDirectory $ProjectDir

# Trigger: at user logon
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: restart on failure, don't stop on idle
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Register
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Xiaoer VideoLab daemon — local yt-dlp video downloader" | Out-Null
Write-Host "  ✓ Task '$TaskName' registered (starts at login)" -ForegroundColor Green

# --- Start the daemon now ---

Write-Host "`n[3/4] Starting daemon..." -ForegroundColor Yellow

# Kill any existing instance
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*server.py*" -or $_.CommandLine -like "*xiaoer*"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Milliseconds 500

# Start via Task Scheduler
Start-ScheduledTask -TaskName $TaskName

# Wait for health
Write-Host "  Waiting for daemon..." -ForegroundColor DarkGray
$ok = $false
$logDir = Join-Path $env:LOCALAPPDATA "xiaoer-videolab"
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:7788/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $ok = $true
            break
        }
    } catch {}
}

if ($ok) {
    Write-Host "  ✓ Daemon running at http://127.0.0.1:7788" -ForegroundColor Green
    Write-Host "  Log: $logDir\xiaoer-videolab.log" -ForegroundColor DarkGray
} else {
    Write-Host "  ✗ Daemon did not start. Check the log:" -ForegroundColor Red
    Write-Host "    Get-Content `"$logDir\xiaoer-videolab.log`" -Tail 20" -ForegroundColor DarkGray
    exit 1
}

# --- Extension instructions ---

Write-Host "`n[4/4] Load the browser extension:" -ForegroundColor Yellow
Write-Host "  1. Open edge://extensions/ (or chrome://extensions/)" -ForegroundColor White
Write-Host "  2. Turn on 'Developer mode' (top-right)" -ForegroundColor White
Write-Host "  3. Click 'Load unpacked'" -ForegroundColor White
Write-Host "  4. Select: $ProjectDir\extension" -ForegroundColor Cyan
Write-Host "  5. Pin the icon to the toolbar." -ForegroundColor White

Write-Host "`nConfiguration:" -ForegroundColor Cyan
if ($cookiesBrowser) {
    Write-Host "  Cookies: $cookiesBrowser (Bilibili/YouTube will use your login)" -ForegroundColor White
} else {
    Write-Host "  Cookies: none (some sites may fail with 412)" -ForegroundColor DarkYellow
}

Write-Host "`nDone! Open any video page and click the toolbar button." -ForegroundColor Green
