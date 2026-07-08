$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$BackendPath = Join-Path $ProjectRoot "backend"
$VendorPath = Join-Path $BackendPath ".vendor"
$env:PYTHONPATH = "$VendorPath;$BackendPath"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
