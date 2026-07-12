param(
    [string]$CarHost = "172.20.10.3",
    [string]$CarUser = "jetson",
    [string]$Password = "",
    [string]$HostKey = "",
    [string]$Container = "",
    [string]$ContainerFilter = "ros-foxy|icar|yahboom",
    [ValidateSet("mapping", "navigation", "none")]
    [string]$Mode = "mapping",
    [int]$Port = 6001,
    [string]$Topic = "/cmd_vel",
    [switch]$ListContainers,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BridgeFile = Join-Path $ProjectRoot "robot\icar_tcp_bridge.py"
$Target = "${CarUser}@${CarHost}"
$RemoteBridgeFile = "/home/$CarUser/icar_tcp_bridge.py"

$UsePutty = -not [string]::IsNullOrWhiteSpace($Password)
$SshExecutable = if ($UsePutty) { "C:\Program Files\PuTTY\plink.exe" } else { "ssh" }
$ScpExecutable = if ($UsePutty) { "C:\Program Files\PuTTY\pscp.exe" } else { "scp" }

if ($UsePutty) {
    if (-not (Test-Path $SshExecutable)) {
        throw "plink.exe not found: $SshExecutable"
    }
    if (-not (Test-Path $ScpExecutable)) {
        throw "pscp.exe not found: $ScpExecutable"
    }
    $SshOptions = @("-batch")
    if ($HostKey) {
        $SshOptions += @("-hostkey", $HostKey)
    }
    $SshOptions += @("-pw", $Password)
    $ScpOptions = @("-batch")
    if ($HostKey) {
        $ScpOptions += @("-hostkey", $HostKey)
    }
    $ScpOptions += @("-pw", $Password)
}
else {
    $SshOptions = @(
        "-o", "ConnectTimeout=8",
        "-o", "ServerAliveInterval=15",
        "-o", "StrictHostKeyChecking=accept-new"
    )
    $ScpOptions = $SshOptions
}

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

function Quote-Bash {
    param(
        [string]$Value
    )

    $EscapedSingleQuote = "'" + '"' + "'" + '"' + "'"
    return "'" + $Value.Replace("'", $EscapedSingleQuote) + "'"
}

function Copy-BridgeFile {
    param(
        [string]$LocalPath,
        [string]$RemotePath
    )

    $CopyArgs = @($ScpOptions) + @($LocalPath, "${Target}:${RemotePath}")
    Write-Host ">> $ScpExecutable $($CopyArgs -join ' ')" -ForegroundColor DarkGray
    & $ScpExecutable @CopyArgs
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not $UsePutty) {
        throw "$ScpExecutable exited with code $LASTEXITCODE"
    }

    Write-Host "pscp returned $LASTEXITCODE, verifying remote file before failing..." -ForegroundColor Yellow
    $VerifyArgs = @($SshOptions) + @($Target, "test -s $(Quote-Bash($RemotePath))")
    & $SshExecutable @VerifyArgs
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Remote file exists; continuing despite pscp exit code." -ForegroundColor Yellow
        return
    }

    throw "$ScpExecutable exited with code $LASTEXITCODE"
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
    $Lines = @(Invoke-ExternalCapture $SshExecutable (@($SshOptions) + @($Target, $RemoteCommand)))
    return $Lines | Where-Object { $_ -and $_ -match $ContainerFilter }
}

function Get-AllRemoteContainerLines {
    $RemoteCommand = "docker ps -a --format '{{.ID}}|{{.Image}}|{{.Names}}|{{.Status}}'"
    return @(Invoke-ExternalCapture $SshExecutable (@($SshOptions) + @($Target, $RemoteCommand))) | Where-Object { $_ -and $_.Trim() }
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

    $Preferred = $Lines | Where-Object { $_ -match "\|yahboomtechnology/ros-foxy:" }
    $RunningPreferred = $Preferred | Where-Object { $_ -match "\|Up " }
    $Running = $Lines | Where-Object { $_ -match "\|Up " }
    if ($RunningPreferred) {
        $Selected = $RunningPreferred[0]
    }
    elseif ($Preferred) {
        $Selected = $Preferred[0]
    }
    elseif ($Running) {
        $Selected = $Running[0]
    }
    else {
        $Selected = $Lines[0]
    }
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

Copy-BridgeFile -LocalPath $BridgeFile -RemotePath $RemoteBridgeFile

$WorkspaceSetup = @(
    "source /opt/ros/foxy/setup.bash"
    "source /root/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash"
    "source /root/yahboomcar_ros2_ws/software/library_ws/install/setup.bash"
) -join " && "

$BringupCommand = "$WorkspaceSetup && ros2 launch yahboomcar_bringup yahboomcar_bringup_X3_launch.py"
$LaunchLabel = ""
$LaunchCommands = @()

if ($Mode -eq "mapping") {
    $LaunchLabel = "mapping"
    $LaunchCommands += "$WorkspaceSetup && ros2 launch yahboomcar_nav map_gmapping_launch.py"
}
elseif ($Mode -eq "navigation") {
    $LaunchLabel = "navigation"
    $LaunchCommands += "$WorkspaceSetup && ros2 launch yahboomcar_nav laser_bringup_launch.py"
}

$RemoteScriptLines = @(
    "set -e"
    "pkill -f '[i]car_tcp_serial_bridge.py' || true"
    "docker start $Container >/dev/null"
    "docker exec $Container bash -lc $(Quote-Bash('test -f /root/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash'))"
    "docker exec $Container bash -lc $(Quote-Bash('test -f /root/yahboomcar_ros2_ws/software/library_ws/install/setup.bash'))"
    "cat '$RemoteBridgeFile' | docker exec -i $Container bash -lc $(Quote-Bash('cat >/root/icar_tcp_bridge.py && chmod 755 /root/icar_tcp_bridge.py'))"
    "docker exec $Container bash -lc $(Quote-Bash(""pkill -f '[i]car_tcp_bridge.py' || true""))"
    "docker exec $Container bash -lc $(Quote-Bash(""pkill -f 'yahboomcar_bringup_X3_launch.py' || true""))"
    "docker exec $Container bash -lc $(Quote-Bash(""pkill -f 'map_gmapping_launch.py' || true""))"
    "docker exec $Container bash -lc $(Quote-Bash(""pkill -f 'laser_bringup_launch.py' || true""))"
    "docker exec $Container bash -lc $(Quote-Bash(""source /opt/ros/foxy/setup.bash && source /root/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash && ros2 pkg prefix yahboomcar_bringup >/tmp/icar_pkg_bringup.log && ros2 pkg prefix yahboomcar_nav >/tmp/icar_pkg_nav.log""))"
    "docker exec -d $Container bash -lc $(Quote-Bash(""$BringupCommand > /tmp/icar_bringup.log 2>&1""))"
    "sleep 5"
)

if ($LaunchCommands) {
    $Index = 0
    foreach ($Command in $LaunchCommands) {
        $LogFile = if ($Index -eq 0) { "/tmp/icar_launch.log" } else { "/tmp/icar_launch_$Index.log" }
        $RemoteScriptLines += "docker exec -d $Container bash -lc $(Quote-Bash(""$Command > $LogFile 2>&1""))"
        $RemoteScriptLines += "sleep 5"
        $Index += 1
    }
}

$RemoteScriptLines += "docker exec -d $Container bash -lc $(Quote-Bash(""$WorkspaceSetup && python3 /root/icar_tcp_bridge.py --host 0.0.0.0 --port $Port --topic $Topic > /tmp/icar_tcp_bridge.log 2>&1""))"
$RemoteScript = [string]::Join(" && ", $RemoteScriptLines)

Invoke-External $SshExecutable (@($SshOptions) + @($Target, $RemoteScript))

Write-Host "Started ROS2 base bringup in container. Log: /tmp/icar_bringup.log" -ForegroundColor Green

if ($LaunchCommands) {
    Write-Host "Started ROS2 $LaunchLabel launch in container. Log: /tmp/icar_launch.log" -ForegroundColor Green
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
