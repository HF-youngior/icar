param(
    [string]$IndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$CacheDir = Join-Path $ProjectRoot ".pip-cache"
$TempDir = Join-Path $ProjectRoot ".tmp-pip"
$UserBaseDir = Join-Path $ProjectRoot ".python-userbase"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating project virtual environment: $VenvDir" -ForegroundColor Cyan
    python -m venv $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    throw "Failed to create virtual environment at $VenvDir"
}

New-Item -ItemType Directory -Force -Path $UserBaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
if (-not $NoCache) {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    $env:PIP_CACHE_DIR = $CacheDir
}
$env:TEMP = $TempDir
$env:TMP = $TempDir
$env:PYTHONUSERBASE = $UserBaseDir
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

Write-Host "Using Python: $VenvPython" -ForegroundColor Cyan
Write-Host "Python user base: $UserBaseDir" -ForegroundColor Gray
Write-Host "Temp dir: $TempDir" -ForegroundColor Gray
if ($NoCache) {
    Write-Host "Pip cache: disabled" -ForegroundColor Gray
}
else {
    Write-Host "Pip cache: $CacheDir" -ForegroundColor Gray
}
Write-Host ""

& $VenvPython -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) {
    throw "ensurepip failed"
}

$PipCommonArgs = @("-i", $IndexUrl)
if ($NoCache) {
    $PipCommonArgs += "--no-cache-dir"
}
else {
    $PipCommonArgs += @("--cache-dir", $CacheDir)
}

& $VenvPython -m pip install --upgrade pip @PipCommonArgs
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed"
}

& $VenvPython -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt") @PipCommonArgs
if ($LASTEXITCODE -ne 0) {
    throw "backend dependency installation failed"
}

Write-Host ""
Write-Host "Backend dependencies installed into project .venv on the F drive." -ForegroundColor Green
Write-Host "Next backend starts will use: $VenvPython" -ForegroundColor Green
