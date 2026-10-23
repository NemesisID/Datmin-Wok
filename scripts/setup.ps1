# Setup sekali jalan untuk Windows PowerShell.
# Jalankan dari folder proyek: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv tidak ditemukan." -ForegroundColor Red
    Write-Host "Pasang dulu dengan perintah berikut, lalu buka PowerShell baru:"
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex"
    exit 1
}

Write-Host "1/4  Memasang dependensi..." -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "uv sync gagal. Baca pesan di atas." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "2/4  Menyiapkan .env..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  .env dibuat dari .env.example. Isi OPENALEX_API_KEY kalau sudah punya."
} else {
    Write-Host "  .env sudah ada, tidak diubah."
}

Write-Host "3/4  Menyiapkan folder data..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force "data" | Out-Null

Write-Host "4/4  Memeriksa instalasi..." -ForegroundColor Cyan
uv run python -c "import fastapi, httpx, pydantic_settings; print('  dependensi ok')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependensi tidak bisa diimpor. Coba hapus .venv lalu jalankan ulang." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Selesai. Langkah berikutnya:" -ForegroundColor Green
Write-Host "  .\scripts\check.ps1     # lint dan tes"
Write-Host "  .\scripts\dev.ps1       # jalankan aplikasi di http://127.0.0.1:8000"
