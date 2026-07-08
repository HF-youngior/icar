$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$LocalEnvPath = Join-Path $ProjectRoot ".env.ps1"
if (Test-Path $LocalEnvPath) {
    . $LocalEnvPath
}
$BackendPath = Join-Path $ProjectRoot "backend"
$VendorPath = Join-Path $BackendPath ".vendor"
$env:PYTHONPATH = "$VendorPath;$BackendPath"
$HostValue = if ($env:ICAR_HOST) { $env:ICAR_HOST } else { "127.0.0.1" }
$PortValue = if ($env:ICAR_PORT) { $env:ICAR_PORT } else { "8000" }
$ReloadArgs = if ($env:ICAR_RELOAD -eq "1") { @("--reload") } else { @() }
python -m uvicorn app.main:app --host $HostValue --port $PortValue @ReloadArgs
