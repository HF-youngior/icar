param(
    [string]$CarHost = "192.168.137.173",
    [string]$CarUser = "jetson",
    [string]$Password = "yahboom",
    [string]$HostKey = "ssh-ed25519 255 SHA256:AJffjk3YWwStux7ZbdKdft3teC8b7Jsubuvv4zMYuD8",
    [int[]]$Ports = @(6000, 6500),
    [string]$Display = ":0",
    [int]$TimeoutMs = 2500,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Target = "${CarUser}@${CarHost}"
$RemoteDir = "/home/$CarUser/Rosmaster-App/rosmaster"
$RemoteApp = "$RemoteDir/app.py"
$RemoteLog = "/tmp/icar_builtin_app.log"
$RemotePid = "/tmp/icar_builtin_app.pid"

$UsePutty = -not [string]::IsNullOrWhiteSpace($Password)
$SshExecutable = if ($UsePutty) { "C:\Program Files\PuTTY\plink.exe" } else { "ssh" }

if ($UsePutty) {
    if (-not (Test-Path $SshExecutable)) {
        throw "plink.exe not found: $SshExecutable"
    }
    $SshOptions = @("-batch")
    if ($HostKey) {
        $SshOptions += @("-hostkey", $HostKey)
    }
    $SshOptions += @("-pw", $Password)
}
else {
    $SshOptions = @(
        "-o", "ConnectTimeout=8",
        "-o", "ServerAliveInterval=15",
        "-o", "StrictHostKeyChecking=accept-new"
    )
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

Write-Host "iCar built-in Rosmaster app setup" -ForegroundColor Cyan
Write-Host "Car:       $Target"
Write-Host "Remote:    $RemoteDir/app.py"
Write-Host "Ports:     $($Ports -join ', ')"
Write-Host "Display:   $Display"
Write-Host ""

$AllPortsOpen = $true
foreach ($Port in $Ports) {
    if (-not (Test-TcpPortFast -HostName $CarHost -TargetPort $Port -ConnectTimeoutMs $TimeoutMs)) {
        $AllPortsOpen = $false
        break
    }
}

if ($AllPortsOpen -and -not $Restart) {
    Write-Host "Ports are already open; app.py appears to be running." -ForegroundColor Green
}
else {
    $KillScript = @(
        "if test -f $(Quote-Bash($RemotePid)); then oldpid=`$(cat $(Quote-Bash($RemotePid)) 2>/dev/null || true); test -n `"`$oldpid`" && kill `"`$oldpid`" 2>/dev/null || true; fi",
        "pkill -f '[i]car_camera_mjpeg_server.py' 2>/dev/null || true",
        "rm -f $(Quote-Bash($RemotePid))"
    ) -join "; "
    Invoke-External $SshExecutable (@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($KillScript))"))

    $StartScript = @(
        "cd $(Quote-Bash($RemoteDir))",
        "test -f app.py",
        "DISPLAY=$(Quote-Bash($Display)) XAUTHORITY=/home/$CarUser/.Xauthority nohup setsid -f python3 $(Quote-Bash($RemoteApp)) </dev/null > $(Quote-Bash($RemoteLog)) 2>&1",
        "sleep 0.8",
        "pgrep -f '[a]pp.py' | head -n 1 > $(Quote-Bash($RemotePid)) || true",
        "echo started-app.py",
        "exit 0"
    ) -join "; "

    Invoke-External $SshExecutable (@($SshOptions) + @($Target, "bash -lc $(Quote-Bash($StartScript))"))
}

Start-Sleep -Seconds 2
$AnyOpen = $false
foreach ($Port in $Ports) {
    if (Test-TcpPortFast -HostName $CarHost -TargetPort $Port -ConnectTimeoutMs $TimeoutMs) {
        $AnyOpen = $true
        Write-Host "Port check passed: ${CarHost}:${Port}" -ForegroundColor Green
    }
    else {
        Write-Host "Port check failed: ${CarHost}:${Port}" -ForegroundColor Yellow
    }
}

if (-not $AnyOpen) {
    Write-Host "The app may still be starting, or app.py may depend on packages/services missing on this car image." -ForegroundColor Yellow
    Write-Host "Inspect car log with:" -ForegroundColor Yellow
    Write-Host "ssh $Target `"tail -n 80 $RemoteLog`"" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "cd $ProjectRoot"
Write-Host ".\scripts\check_car_connection.ps1 -CarHost `"$CarHost`""
