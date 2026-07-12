param(
    [string]$CarHost = "192.168.137.173",
    [int]$CarPort = 6000,
    [int]$TimeoutMs = 1800
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Test-TcpPortFast {
    param(
        [string]$HostName,
        [int]$TargetPort,
        [int]$ConnectTimeoutMs
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Task = $Client.ConnectAsync($HostName, $TargetPort)
        if (-not $Task.Wait($ConnectTimeoutMs)) {
            return $false
        }
        return $Client.Connected
    }
    catch {
        return $false
    }
    finally {
        $Client.Close()
    }
}

# Force these values every time. PowerShell keeps old $env:* values in the
# current window, and a stale ICAR_CAR_PORT=6001 makes the Web UI look offline.
$env:ICAR_CAR_ADAPTER = "tcp"
$env:ICAR_CAR_HOST = $CarHost
$env:ICAR_CAR_PORT = "$CarPort"

Write-Host "Backend will connect to car at $($env:ICAR_CAR_HOST):$($env:ICAR_CAR_PORT)" -ForegroundColor Cyan
Write-Host "Default port 6000 uses the car's built-in Rosmaster app service." -ForegroundColor DarkGray
Write-Host "Port 6001 is only for our optional custom Rosmaster bridge." -ForegroundColor DarkGray

if (Test-TcpPortFast -HostName $CarHost -TargetPort $CarPort -ConnectTimeoutMs $TimeoutMs) {
    Write-Host "Car control port check passed: ${CarHost}:${CarPort}" -ForegroundColor Green
}
else {
    Write-Host "Car control port check failed: ${CarHost}:${CarPort}" -ForegroundColor Yellow
    Write-Host "The backend can still start, but the Web robot status will be offline until this port opens." -ForegroundColor Yellow
    Write-Host "Run .\scripts\check_car_connection.ps1 -CarHost `"$CarHost`" for a quick diagnosis." -ForegroundColor Yellow
}

& (Join-Path $PSScriptRoot "start_backend.ps1")
