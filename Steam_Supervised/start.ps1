param(
    [switch]$Reload,
    [int]$Port = 8000,
    [switch]$StrictPort
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeVenvPython = Join-Path $projectRoot ".runtime-venv\Scripts\python.exe"
$legacyVenvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pidFile = Join-Path $projectRoot ".server.pid"
$portFile = Join-Path $projectRoot ".server.port"
$stdoutLog = Join-Path $projectRoot ".server.stdout.log"
$stderrLog = Join-Path $projectRoot ".server.stderr.log"

function Test-PythonExecutable {
    param([string]$CandidatePath)

    if (-not (Test-Path $CandidatePath)) {
        return $false
    }

    try {
        & $CandidatePath --version | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-PortAvailable {
    param([int]$PortToCheck)

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Parse("127.0.0.1"),
            $PortToCheck
        )
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Find-FreePort {
    param(
        [int]$StartPort,
        [int]$Attempts = 20
    )

    for ($candidate = $StartPort; $candidate -lt ($StartPort + $Attempts); $candidate++) {
        if (Test-PortAvailable -PortToCheck $candidate) {
            return $candidate
        }
    }

    throw "Could not find a free port in the range $StartPort-$($StartPort + $Attempts - 1)."
}

function Test-HealthEndpoint {
    param([int]$PortToCheck)

    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:$PortToCheck/health" `
            -UseBasicParsing `
            -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-StartupLogReady {
    param(
        [string]$LogPath,
        [int]$PortToCheck
    )

    if (-not (Test-Path $LogPath)) {
        return $false
    }

    $pattern = "Uvicorn running on http://127\.0\.0\.1:$PortToCheck"
    $content = Get-Content -Path $LogPath -ErrorAction SilentlyContinue
    return $content -match $pattern
}

function Get-LoggedServerPid {
    param(
        [string]$LogPath,
        [switch]$ReloadMode
    )

    if (-not (Test-Path $LogPath)) {
        return $null
    }

    $content = Get-Content -Path $LogPath -ErrorAction SilentlyContinue
    if ($ReloadMode) {
        $reloaderLine = $content | Select-String -Pattern "Started reloader process \[(\d+)\]" | Select-Object -Last 1
        if ($reloaderLine -and $reloaderLine.Matches.Count -gt 0) {
            return [int]$reloaderLine.Matches[0].Groups[1].Value
        }
    }

    $serverLine = $content | Select-String -Pattern "Started server process \[(\d+)\]" | Select-Object -Last 1
    if ($serverLine -and $serverLine.Matches.Count -gt 0) {
        return [int]$serverLine.Matches[0].Groups[1].Value
    }

    return $null
}

if (Test-PythonExecutable -CandidatePath $runtimeVenvPython) {
    $venvPython = $runtimeVenvPython
} elseif (Test-PythonExecutable -CandidatePath $legacyVenvPython) {
    $venvPython = $legacyVenvPython
} else {
    Write-Host "No usable project Python runtime was found." -ForegroundColor Red
    Write-Host "Expected one of these interpreters to work:" -ForegroundColor Yellow
    Write-Host "  $runtimeVenvPython"
    Write-Host "  $legacyVenvPython"
    exit 1
}

if (Test-Path $pidFile) {
    try {
        $existingPid = Get-Content $pidFile | Select-Object -First 1
        if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
            $existingPort = 8000
            if (Test-Path $portFile) {
                $storedPort = Get-Content $portFile | Select-Object -First 1
                if ($storedPort) {
                    $existingPort = $storedPort
                }
            }
            Write-Host "Service already appears to be running. PID: $existingPid" -ForegroundColor Yellow
            Write-Host "Dashboard: http://127.0.0.1:$existingPort/watch-items/dashboard" -ForegroundColor Yellow
            Write-Host "Run .\stop.ps1 first if you want to restart it." -ForegroundColor Yellow
            exit 0
        }
    } catch {
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Remove-Item $portFile -Force -ErrorAction SilentlyContinue
Remove-Item $stdoutLog -Force -ErrorAction SilentlyContinue
Remove-Item $stderrLog -Force -ErrorAction SilentlyContinue

$selectedPort = $Port
if (-not (Test-PortAvailable -PortToCheck $selectedPort)) {
    if ($StrictPort) {
        Write-Host "Port $selectedPort is already in use." -ForegroundColor Red
        Write-Host "Run .\stop.ps1 or choose another port with -Port." -ForegroundColor Yellow
        exit 1
    }

    $alternatePort = Find-FreePort -StartPort ($selectedPort + 1)
    Write-Host "Port $selectedPort is busy. Switching to http://127.0.0.1:$alternatePort" -ForegroundColor Yellow
    $selectedPort = $alternatePort
}

$arguments = @(
    (Join-Path $projectRoot "run_server.py"),
    "--port",
    "$selectedPort"
)

$modeLabel = "normal"
if ($Reload) {
    $arguments += "--reload"
    $modeLabel = "reload"
}

$process = Start-Process `
    -FilePath $venvPython `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

$deadline = (Get-Date).AddSeconds(15)
$healthy = $false
$trackedPid = $process.Id

while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        $loggedPid = Get-LoggedServerPid -LogPath $stderrLog -ReloadMode:$Reload
        if ($loggedPid -and (Get-Process -Id $loggedPid -ErrorAction SilentlyContinue)) {
            $trackedPid = $loggedPid
        } else {
            break
        }
    }

    if (
        (Test-HealthEndpoint -PortToCheck $selectedPort) -or
        (Test-StartupLogReady -LogPath $stderrLog -PortToCheck $selectedPort)
    ) {
        $loggedPid = Get-LoggedServerPid -LogPath $stderrLog -ReloadMode:$Reload
        if ($loggedPid -and (Get-Process -Id $loggedPid -ErrorAction SilentlyContinue)) {
            $trackedPid = $loggedPid
        }
        $healthy = $true
        break
    }

    Start-Sleep -Milliseconds 500
}

if (-not $healthy) {
    Stop-Process -Id $trackedPid -Force -ErrorAction SilentlyContinue
    if ($trackedPid -ne $process.Id) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Steam Price Monitor failed to start." -ForegroundColor Red
    if (Test-Path $stderrLog) {
        $errorOutput = (Get-Content $stderrLog -ErrorAction SilentlyContinue | Select-Object -Last 10) -join [Environment]::NewLine
        if ($errorOutput) {
            Write-Host ""
            Write-Host "Last error output:" -ForegroundColor Yellow
            Write-Host $errorOutput
        }
    }
    if ((-not (Test-Path $stderrLog)) -and (Test-Path $stdoutLog)) {
        $standardOutput = (Get-Content $stdoutLog -ErrorAction SilentlyContinue | Select-Object -Last 10) -join [Environment]::NewLine
        if ($standardOutput) {
            Write-Host ""
            Write-Host "Last startup output:" -ForegroundColor Yellow
            Write-Host $standardOutput
        }
    }
    Write-Host ""
    Write-Host "Try again with .\start.ps1 -Port 8010 or inspect .server.stderr.log" -ForegroundColor Yellow
    exit 1
}

$trackedPid | Set-Content $pidFile
$selectedPort | Set-Content $portFile

Write-Host "Steam Price Monitor started ($modeLabel mode)." -ForegroundColor Green
Write-Host "PID: $trackedPid"
Write-Host "Dashboard: http://127.0.0.1:$selectedPort/watch-items/dashboard"
Write-Host "Health: http://127.0.0.1:$selectedPort/health"
Write-Host "Stop with: .\stop.ps1"
Write-Host "Python: $venvPython"
Write-Host "Logs: .server.stdout.log / .server.stderr.log"
