$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot ".server.pid"
$portFile = Join-Path $projectRoot ".server.port"

if (-not (Test-Path $pidFile)) {
    Write-Host "No running service record was found." -ForegroundColor Yellow
    exit 0
}

$serverPid = Get-Content $pidFile | Select-Object -First 1

if (-not $serverPid) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "PID file was empty and has been cleaned up." -ForegroundColor Yellow
    exit 0
}

$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($process) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $serverPid" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Stop-Process -Id $serverPid -Force
    Write-Host "Service stopped. PID: $serverPid" -ForegroundColor Green
} else {
    Write-Host "Process was not running. PID file has been cleaned up." -ForegroundColor Yellow
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item $portFile -Force -ErrorAction SilentlyContinue
