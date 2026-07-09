param(
    [string]$CarHost = "172.20.10.3",
    [string]$CarUser = "jetson",
    [string]$Container = "",
    [string]$ContainerFilter = "ros-foxy|icar|yahboom",
    [ValidateSet("mapping", "navigation", "none")]
    [string]$Mode = "mapping",
    [int]$Port = 6000,
    [string]$Topic = "/cmd_vel",
    [switch]$ListContainers,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BridgeFile = Join-Path $ProjectRoot "robot\icar_tcp_bridge.py"
$Target = "${CarUser}@${CarHost}"
$RemoteBridgeFile = "/home/$CarUser/icar_tcp_bridge.py"
$SshOptions = @(
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=15",
    "-o", "StrictHostKeyChecking=accept-new"
)

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Invoke-ExternalCapture {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    $Output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
    return $Output
}

function Test-TcpPortFast {
    param(
        [string]$HostName,
        [int]$TargetPort,
        [int]$TimeoutMs = 3000
    )

    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $ConnectTask = $Client.ConnectAsync($HostName, $TargetPort)
        if (-not $ConnectTask.Wait($TimeoutMs)) {
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

if (-not (Test-Path $BridgeFile)) {
    throw "Bridge file not found: $BridgeFile"
}

function Get-RemoteContainerLines {
    $RemoteCommand = "docker ps -a --format '{{.ID}}|{{.Image}}|{{.Names}}|{{.Status}}'"
    $Lines = @(Invoke-ExternalCapture "ssh" (@($SshOptions) + @($Target, $RemoteCommand)))
    return $Lines | Where-Object { $_ -and $_ -match $ContainerFilter }
}

function Get-AllRemoteContainerLines {
    $RemoteCommand = "docker ps -a --format '{{.ID}}|{{.Image}}|{{.Names}}|{{.Status}}'"
    return @(Invoke-ExternalCapture "ssh" (@($SshOptions) + @($Target, $RemoteCommand))) | Where-Object { $_ -and $_.Trim() }
}

function Resolve-ContainerId {
    if ($Container) {
        return $Container
    }

    $Lines = @(Get-RemoteContainerLines) | Where-Object { $_ -and $_.Trim() }
    if (-not $Lines) {
        $AllLines = @(Get-AllRemoteContainerLines)
        if ($AllLines) {
            Write-Host "No container matched filter '$ContainerFilter'. Here are all remote containers:" -ForegroundColor Yellow
            $AllLines | ForEach-Object { Write-Host $_ }
        }
        throw "No container matched filter '$ContainerFilter'. You can rerun with -Container <ID> to specify one manually."
    }

    $Running = $Lines | Where-Object { $_ -match "\|Up " }
    $Selected = if ($Running) { $Running[0] } else { $Lines[0] }
    $Parts = $Selected -split "\|"
    if ($Parts.Count -lt 1 -or -not $Parts[0]) {
        throw "Failed to parse container info: $Selected"
    }
    return $Parts[0].Trim()
}

Write-Host "iCar SSH bridge setup" -ForegroundColor Cyan
Write-Host "Car:       $Target"
Write-Host "Filter:    $ContainerFilter"
Write-Host "Mode:      $Mode"
Write-Host "Port:      $Port"
Write-Host "Topic:     $Topic"
Write-Host ""

if ($ListContainers) {
    $Lines = @(Get-RemoteContainerLines) | Where-Object { $_ -and $_.Trim() }
    if ($Lines) {
        Write-Host "Matched containers:" -ForegroundColor Cyan
        $Lines | ForEach-Object { Write-Host $_ }
    }
    else {
        Write-Host "No containers matched filter '$ContainerFilter'." -ForegroundColor Yellow
        $AllLines = @(Get-AllRemoteContainerLines)
        if ($AllLines) {
            Write-Host "All remote containers:" -ForegroundColor Cyan
            $AllLines | ForEach-Object { Write-Host $_ }
        }
    }
    exit 0
}

$Container = Resolve-ContainerId
Write-Host "Container: $Container" -ForegroundColor Green
Write-Host ""

Invoke-External "scp" (@($SshOptions) + @($BridgeFile, "${Target}:${RemoteBridgeFile}"))

if ($Mode -ne "none") {
    $LaunchAlias = if ($Mode -eq "navigation") { "n1" } else { "m1" }
}
else {
    $LaunchAlias = ""
}

$RemoteScriptLines = @(
    "set -e"
    "pkill -f '[i]car_tcp_serial_bridge.py' || true"
    "docker start $Container >/dev/null"
    "cat '$RemoteBridgeFile' | docker exec -i $Container bash -lc 'cat >/root/icar_tcp_bridge.py && chmod 755 /root/icar_tcp_bridge.py'"
    "docker exec $Container bash -lc ""pkill -f '[i]car_tcp_bridge.py' || true"""
)

if ($LaunchAlias) {
    $RemoteScriptLines += "docker exec -d $Container bash -ic '$LaunchAlias > /tmp/icar_launch.log 2>&1'"
}

$RemoteScriptLines += "docker exec -d $Container bash -ic 'source /opt/ros/foxy/setup.bash 2>/dev/null || true; python3 /root/icar_tcp_bridge.py --host 0.0.0.0 --port $Port --topic $Topic > /tmp/icar_tcp_bridge.log 2>&1'"
$RemoteScript = [string]::Join(" && ", $RemoteScriptLines)

Invoke-External "ssh" (@($SshOptions) + @($Target, $RemoteScript))

if ($LaunchAlias) {
    Write-Host "Started ROS2 launch alias '$LaunchAlias' in container. Log: /tmp/icar_launch.log" -ForegroundColor Green
}

Write-Host "Started TCP-to-ROS2 bridge. Log: /tmp/icar_tcp_bridge.log" -ForegroundColor Green

if (-not $SkipPortCheck) {
    Start-Sleep -Seconds 1
    if (Test-TcpPortFast -HostName $CarHost -TargetPort $Port) {
        Write-Host "Port check passed: ${CarHost}:${Port}" -ForegroundColor Green
    }
    else {
        Write-Host "Port check failed: ${CarHost}:${Port}" -ForegroundColor Yellow
        Write-Host "You can inspect logs with:" -ForegroundColor Yellow
        Write-Host "ssh $Target `"docker exec $Container bash -lc 'tail -n 40 /tmp/icar_tcp_bridge.log /tmp/icar_launch.log 2>/dev/null'`"" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Next, start the local backend in another PowerShell:" -ForegroundColor Cyan
Write-Host "cd $ProjectRoot"
Write-Host '$env:ICAR_CAR_ADAPTER="tcp"'
Write-Host "`$env:ICAR_CAR_HOST=`"$CarHost`""
Write-Host "`$env:ICAR_CAR_PORT=`"$Port`""
Write-Host ".\scripts\start_backend.ps1"
