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
$HostValue = if ($env:ICAR_HOST) { $env:ICAR_HOST } else { "0.0.0.0" }
$PortValue = if ($env:ICAR_PORT) { $env:ICAR_PORT } else { "8000" }
$ReloadArgs = if ($env:ICAR_RELOAD -eq "1") { @("--reload") } else { @() }

function Get-LocalIpv4Candidates {
    $Entries = @()
    try {
        $Configs = Get-NetIPConfiguration -ErrorAction Stop | Where-Object {
            $_.NetAdapter.Status -eq "Up" -and $_.IPv4Address
        }
        foreach ($Config in $Configs) {
            foreach ($Address in @($Config.IPv4Address)) {
                if (-not $Address.IPAddress) {
                    continue
                }
                if ($Address.IPAddress -eq "127.0.0.1" -or $Address.IPAddress -like "169.254.*") {
                    continue
                }
                $Entries += [PSCustomObject]@{
                    InterfaceAlias = $Config.InterfaceAlias
                    IPAddress = $Address.IPAddress
                }
            }
        }
    }
    catch {
        return @()
    }

    return $Entries |
        Sort-Object IPAddress, InterfaceAlias -Unique
}

Write-Host ""
Write-Host "iCar backend starting..." -ForegroundColor Cyan
Write-Host "Bind host: $HostValue" -ForegroundColor Gray
Write-Host "Bind port: $PortValue" -ForegroundColor Gray
Write-Host ""

if ($HostValue -eq "0.0.0.0") {
    Write-Host "Local access:" -ForegroundColor Green
    Write-Host "  Dashboard: http://127.0.0.1:${PortValue}/dashboard"
    Write-Host "  Control:   http://127.0.0.1:${PortValue}/control"
    Write-Host ""
    Write-Host "Shareable LAN URLs (phone and car should be on the same hotspot):" -ForegroundColor Green
    $Candidates = @(Get-LocalIpv4Candidates)
    if ($Candidates) {
        foreach ($Candidate in $Candidates) {
            Write-Host "  [$($Candidate.InterfaceAlias)] http://$($Candidate.IPAddress):${PortValue}/control"
        }
        Write-Host ""
        Write-Host "Usually the Windows hotspot address is something like 192.168.137.1." -ForegroundColor Yellow
        Write-Host "You can send one of the URLs above to your phone in WeChat." -ForegroundColor Yellow
    }
    else {
        Write-Host "  No LAN IPv4 address detected yet. If the hotspot is not ready, reconnect and restart." -ForegroundColor Yellow
    }
}
elseif ($HostValue -eq "127.0.0.1" -or $HostValue -eq "localhost") {
    Write-Host "Local access only:" -ForegroundColor Yellow
    Write-Host "  Dashboard: http://127.0.0.1:${PortValue}/dashboard"
    Write-Host "  Control:   http://127.0.0.1:${PortValue}/control"
    Write-Host ""
    Write-Host "To allow phone access on the same hotspot, run:" -ForegroundColor Yellow
    Write-Host '  $env:ICAR_HOST="0.0.0.0"'
}
else {
    Write-Host "Access URLs:" -ForegroundColor Green
    Write-Host "  Dashboard: http://${HostValue}:${PortValue}/dashboard"
    Write-Host "  Control:   http://${HostValue}:${PortValue}/control"
}

Write-Host ""
Write-Host "If Windows Firewall asks, allow access on Private networks." -ForegroundColor Yellow
Write-Host ""

python -m uvicorn app.main:app --host $HostValue --port $PortValue @ReloadArgs
