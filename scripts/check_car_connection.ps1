param(
    [string]$CarHost = "192.168.137.173",
    [int[]]$Ports = @(22, 6000, 6001, 6500),
    [int]$TimeoutMs = 1800
)

$ErrorActionPreference = "Stop"

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

Write-Host "Checking iCar connection: $CarHost" -ForegroundColor Cyan
Write-Host ""

foreach ($Port in $Ports) {
    $Name = switch ($Port) {
        22 { "SSH login" }
        6000 { "Built-in Rosmaster app control" }
        6001 { "Optional custom Rosmaster bridge" }
        6500 { "Built-in Rosmaster web/app service" }
        default { "TCP service" }
    }

    if (Test-TcpPortFast -HostName $CarHost -TargetPort $Port -ConnectTimeoutMs $TimeoutMs) {
        Write-Host ("  {0,-5} open     {1}" -f $Port, $Name) -ForegroundColor Green
    }
    else {
        Write-Host ("  {0,-5} closed   {1}" -f $Port, $Name) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Recommended backend command for the current course car:" -ForegroundColor Cyan
Write-Host "  .\scripts\start_backend_car_ssh.ps1 -CarHost `"$CarHost`" -CarPort 6000"
Write-Host ""
Write-Host "If 6000 is open but the Web still shows offline, stop the old backend window and start it again with the command above." -ForegroundColor Yellow
