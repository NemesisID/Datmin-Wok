# Jalankan aplikasi untuk pengembangan.
# Contoh: .\scripts\dev.ps1 -Port 8001

param(
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host ".venv belum ada. Jalankan .\scripts\setup.ps1 dulu." -ForegroundColor Red
    exit 1
}

$uvArgs = @("run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port)
if (-not $NoReload) {
    $uvArgs += "--reload"
}

Write-Host "Aplikasi: http://127.0.0.1:$Port   (Ctrl+C untuk berhenti)" -ForegroundColor Cyan
uv @uvArgs
