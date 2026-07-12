param(
    [string]$CarHost = "192.168.137.173",
    [string]$CarUser = "jetson",
    [string]$Password = "yahboom",
    [string]$HostKey = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8",
    [int]$Port = 8080,
    [string]$Device = "auto",
    [int]$Width = 640,
    [int]$Height = 480,
    [int]$Fps = 12,
    [int]$TimeoutMs = 2500
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CameraFile = Join-Path $ProjectRoot "robot\camera_mjpeg_server.py"
$Target = "${CarUser}@${CarHost}"
$RemoteFile = "/home/$CarUser/icar_camera_mjpeg_server.py"
$RemoteLog = "/tmp/icar_camera_mjpeg_server.log"
$RemotePid = "/tmp/icar_camera_mjpeg_server.pid"

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

function Copy-CameraFile {
    $CopyArgs = @($ScpOptions) + @($CameraFile, "${Target}:${RemoteFile}")
    Write-Host ">> $ScpExecutable $($CopyArgs -join ' ')" -ForegroundColor DarkGray
    & $ScpExecutable @CopyArgs
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not $UsePutty) {
        throw "$ScpExecutable exited with code $LASTEXITCODE"
    }

    Write-Host "pscp returned $LASTEXITCODE, verifying remote camera file before failing..." -ForegroundColor Yellow
    & $SshExecutable @(@($SshOptions) + @($Target, "test -s $(Quote-Bash($RemoteFile))"))
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Remote camera file exists; continuing despite pscp exit code." -ForegroundColor Yellow
        return
    }

    throw "$ScpExecutable exited with code $LASTEXITCODE"
}

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

if (-not (Test-Path $CameraFile)) {
    throw "Camera server file not found: $CameraFile"
}

Write-Host "iCar camera MJPEG setup" -ForegroundColor Cyan
Write-Host "Car:       $Target"
Write-Host "Remote:    $RemoteFile"
Write-Host "Port:      $Port"
Write-Host "Device:    $Device"
Write-Host ""

Copy-CameraFile

$StopScript = @(
    "if test -f $(Quote-Bash($RemotePid)); then",
    "oldpid=`$(cat $(Quote-Bash($RemotePid)) 2>/dev/null || true);",
    "if test -n `"`$oldpid`" && ps -p `"`$oldpid`" -o args= 2>/dev/null | grep -q 'icar_camera_mjpeg_server.py'; then kill `"`$oldpid`" 2>/dev/null || true; fi;",
    "rm -f $(Quote-Bash($RemotePid));",
    "fi"
) -join " "

$StartScript = @(
    $StopScript,
    "python3 -m py_compile $(Quote-Bash($RemoteFile))",
    "setsid python3 $(Quote-Bash($RemoteFile)) --host 0.0.0.0 --port $Port --device $(Quote-Bash($Device)) --width $Width --height $Height --fps $Fps </dev/null > $(Quote-Bash($RemoteLog)) 2>&1 & echo `$! > $(Quote-Bash($RemotePid))",
    "exit 0"
) -join "; "

Invoke-External $SshExecutable (@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($StartScript))"))

Start-Sleep -Seconds 2
if (Test-TcpPortFast -HostName $CarHost -TargetPort $Port -ConnectTimeoutMs $TimeoutMs) {
    Write-Host "Port check passed: ${CarHost}:${Port}" -ForegroundColor Green
    Write-Host "Vision URL: http://${CarHost}:${Port}/?action=stream" -ForegroundColor Green
}
else {
    Write-Host "Port check failed: ${CarHost}:${Port}" -ForegroundColor Yellow
    Write-Host "Inspect car camera log with:" -ForegroundColor Yellow
    Write-Host "ssh $Target `"tail -n 80 $RemoteLog`"" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "cd $ProjectRoot"
Write-Host ".\scripts\check_car_connection.ps1 -CarHost `"$CarHost`""
