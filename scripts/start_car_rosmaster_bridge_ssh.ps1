param(
    [string]$CarHost = "192.168.137.173",
    [string]$CarUser = "jetson",
    [string]$Password = "yahboom",
    [string]$HostKey = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8",
    [int]$Port = 6001,
    [int]$Speed = 50,
    [double]$PulseTimeoutSec = 0.45,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BridgeFile = Join-Path $ProjectRoot "robot\rosmaster_tcp_bridge.py"
$Target = "${CarUser}@${CarHost}"
$RemoteDir = "/home/$CarUser/Rosmaster-App/rosmaster"
$RemoteBridgeFile = "$RemoteDir/icar_rosmaster_tcp_bridge.py"

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
    $ScpOptions = @("-batch")
    if ($HostKey) {
        $SshOptions += @("-hostkey", $HostKey)
        $ScpOptions += @("-hostkey", $HostKey)
    }
    $SshOptions += @("-pw", $Password)
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

function Quote-Bash {
    param([string]$Value)
    $EscapedSingleQuote = "'" + '"' + "'" + '"' + "'"
    return "'" + $Value.Replace("'", $EscapedSingleQuote) + "'"
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

function Copy-BridgeFile {
    $CopyArgs = @($ScpOptions) + @($BridgeFile, "${Target}:${RemoteBridgeFile}")
    Write-Host ">> $ScpExecutable $($CopyArgs -join ' ')" -ForegroundColor DarkGray
    & $ScpExecutable @CopyArgs
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not $UsePutty) {
        throw "$ScpExecutable exited with code $LASTEXITCODE"
    }

    Write-Host "pscp returned $LASTEXITCODE, verifying remote file before failing..." -ForegroundColor Yellow
    & $SshExecutable @(@($SshOptions) + @($Target, "test -s $(Quote-Bash($RemoteBridgeFile))"))
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

function Show-RemoteBridgeDiagnostics {
    $DiagScript = @(
        "echo '--- process ---'",
        "pgrep -af '[i]car_rosmaster_tcp_bridge.py' || true",
        "echo '--- listening:$Port ---'",
        "(ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null || true) | grep ':$Port ' || true",
        "echo '--- log:/tmp/icar_rosmaster_tcp_bridge.log ---'",
        "tail -n 120 /tmp/icar_rosmaster_tcp_bridge.log 2>/dev/null || true"
    ) -join "; "

    Write-Host ""
    Write-Host "Remote bridge diagnostics:" -ForegroundColor Yellow
    & $SshExecutable @(@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($DiagScript))"))
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Remote diagnostics command exited with code $LASTEXITCODE" -ForegroundColor Yellow
    }
}

if (-not (Test-Path $BridgeFile)) {
    throw "Bridge file not found: $BridgeFile"
}

Write-Host "iCar Rosmaster SSH bridge setup" -ForegroundColor Cyan
Write-Host "Backup path only. Prefer the built-in 6000 service when it is open." -ForegroundColor Yellow
Write-Host "Car:       $Target"
Write-Host "Remote:    $RemoteBridgeFile"
Write-Host "Port:      $Port"
Write-Host "Speed:     $Speed"
Write-Host "Pulse stop: ${PulseTimeoutSec}s"
Write-Host ""

Copy-BridgeFile

$KillScript = "pkill -f '[i]car_rosmaster_tcp_bridge.py' || true; pkill -f '[r]osmaster_test.py' || true"
$StartScript = @(
    "cd $(Quote-Bash($RemoteDir))",
    "nohup setsid -f python3 $(Quote-Bash($RemoteBridgeFile)) --host 0.0.0.0 --port $Port --speed $Speed --pulse-timeout-sec $PulseTimeoutSec </dev/null > /tmp/icar_rosmaster_tcp_bridge.log 2>&1",
    "sleep 0.4",
    "pgrep -f '[i]car_rosmaster_tcp_bridge.py' | head -n 1 > /tmp/icar_rosmaster_tcp_bridge.pid || true",
    "echo started-icar-rosmaster-bridge",
    "exit 0"
) -join "; "

Invoke-External $SshExecutable (@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($KillScript))"))
Invoke-External $SshExecutable (@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($StartScript))"))

Write-Host "Started Rosmaster TCP bridge. Log: /tmp/icar_rosmaster_tcp_bridge.log" -ForegroundColor Green

if (-not $SkipPortCheck) {
    Start-Sleep -Seconds 1
    if (Test-TcpPortFast -HostName $CarHost -TargetPort $Port) {
        Write-Host "Port check passed: ${CarHost}:${Port}" -ForegroundColor Green
    }
    else {
        Write-Host "Port check failed: ${CarHost}:${Port}" -ForegroundColor Yellow
        Write-Host "Inspect logs with:" -ForegroundColor Yellow
        Write-Host "ssh $Target `"tail -n 80 /tmp/icar_rosmaster_tcp_bridge.log`"" -ForegroundColor Yellow
        Show-RemoteBridgeDiagnostics
    }
}

Write-Host ""
Write-Host "Next, start the local backend:" -ForegroundColor Cyan
Write-Host "cd $ProjectRoot"
Write-Host '$env:ICAR_CAR_ADAPTER="tcp"'
Write-Host "`$env:ICAR_CAR_HOST=`"$CarHost`""
Write-Host "`$env:ICAR_CAR_PORT=`"$Port`""
Write-Host ".\scripts\start_backend.ps1"
