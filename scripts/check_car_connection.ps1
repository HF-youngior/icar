param(
    [string]$CarHost = "192.168.137.173",
    [int[]]$Ports = @(22, 6000, 6001, 6500, 8080, 8081),
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

$Results = @{}
foreach ($Port in $Ports) {
    $Name = switch ($Port) {
        22 { "SSH login" }
        6000 { "Built-in Rosmaster app control" }
        6001 { "Optional custom Rosmaster bridge" }
        6500 { "Built-in Rosmaster web/app service" }
        8080 { "Camera stream candidate" }
        8081 { "Camera stream candidate" }
        default { "TCP service" }
    }

    $IsOpen = Test-TcpPortFast -HostName $CarHost -TargetPort $Port -ConnectTimeoutMs $TimeoutMs
    $Results[$Port] = $IsOpen
    if ($IsOpen) {
        Write-Host ("  {0,-5} open     {1}" -f $Port, $Name) -ForegroundColor Green
    }
    else {
        Write-Host ("  {0,-5} closed   {1}" -f $Port, $Name) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Recommended next step:" -ForegroundColor Cyan
if ($Results[6000]) {
    Write-Host "  .\scripts\start_backend_car_ssh.ps1 -CarHost `"$CarHost`" -CarPort 6000"
    Write-Host "6000 is open, so use the car/app TCP service." -ForegroundColor Green
}
elseif ($Results[6001]) {
    Write-Host "  .\scripts\start_backend_car_ssh.ps1 -CarHost `"$CarHost`" -CarPort 6001"
    Write-Host "6000 is closed, but 6001 is open. Use our custom Rosmaster bridge for Web driving." -ForegroundColor Green
}
else {
    Write-Host "  .\scripts\start_car_rosmaster_bridge_ssh.ps1 -CarHost `"$CarHost`""
    Write-Host "Neither 6000 nor 6001 is open. Start the custom Rosmaster bridge first, then run the backend on 6001." -ForegroundColor Yellow
}

if (-not ($Results[6500] -or $Results[8080] -or $Results[8081])) {
    Write-Host ""
    Write-Host "Camera/HTTP ports are closed. To start our lightweight MJPEG camera service from this computer:" -ForegroundColor Yellow
    Write-Host "  .\scripts\start_car_camera_ssh.ps1 -CarHost `"$CarHost`"" -ForegroundColor Yellow
    Write-Host "If that fails, try the car's built-in app.py service:" -ForegroundColor Yellow
    Write-Host "  .\scripts\start_car_builtin_app_ssh.ps1 -CarHost `"$CarHost`"" -ForegroundColor Yellow
}
