# Setup sekali jalan untuk Windows PowerShell.
# Jalankan dari folder proyek: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# uv menulis progres ke stderr. Tanpa pembungkus ini, PowerShell dengan
# ErrorActionPreference=Stop menganggapnya gagal padahal exit code-nya 0.
function Invoke-Uv {
    param([Parameter(Mandatory)][string[]]$Argumen)
    $sebelum = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & uv @Argumen 2>&1 | ForEach-Object { Write-Host $_ }
    $kode = $LASTEXITCODE
    $ErrorActionPreference = $sebelum
    return $kode
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv tidak ditemukan." -ForegroundColor Red
    Write-Host "Pasang dulu dengan perintah berikut, lalu buka PowerShell baru:"
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex"
    exit 1
}

Write-Host "1/5  Memasang dependensi..." -ForegroundColor Cyan
$kode = Invoke-Uv "sync"
if ($kode -ne 0) {
    Write-Host "uv sync gagal. Baca pesan di atas." -ForegroundColor Red
    exit $kode
}

Write-Host "2/5  Menyiapkan .env..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  .env dibuat dari .env.example."
} else {
    $isiEnv = Get-Content ".env" -Raw
    $tambahan = @()
    foreach ($baris in (Get-Content ".env.example")) {
        if ($baris -match "^\s*#" -or $baris -match "^\s*$") { continue }
        $kunci = ($baris -split "=", 2)[0]
        if ($isiEnv -notmatch ("(?m)^" + [regex]::Escape($kunci) + "=")) {
            $tambahan += $baris
        }
    }
    if ($tambahan.Count -gt 0) {
        $isiEnv = $isiEnv.TrimEnd() + "`r`n`r`n# Ditambahkan setup.ps1`r`n" + ($tambahan -join "`r`n") + "`r`n"
        Set-Content -Path ".env" -Value $isiEnv -Encoding ascii -NoNewline
        Write-Host "  $($tambahan.Count) variabel baru dari .env.example ditambahkan."
    } else {
        Write-Host "  .env sudah lengkap."
    }
}

$isi = Get-Content ".env" -Raw
if ($isi -match "(?m)^SECRET_KEY=\s*$") {
    $rahasia = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
    $isi = $isi -replace "(?m)^SECRET_KEY=\s*$", "SECRET_KEY=$rahasia"
    Set-Content -Path ".env" -Value $isi -Encoding ascii -NoNewline
    Write-Host "  SECRET_KEY acak dibuat untuk sesi admin."
}

Write-Host "3/5  Menyiapkan folder data..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force "data" | Out-Null

Write-Host "4/5  Menjalankan migrasi..." -ForegroundColor Cyan
$kode = Invoke-Uv "run", "python", "-m", "app.cli", "init-db"
if ($kode -ne 0) {
    Write-Host "Migrasi gagal. Baca pesan di atas." -ForegroundColor Red
    exit $kode
}

Write-Host "5/5  Memeriksa instalasi dan taksonomi..." -ForegroundColor Cyan
$kode = Invoke-Uv "run", "python", "-c", "import fastapi, httpx, sqlmodel, pydantic_settings; print('  dependensi ok')"
if ($kode -ne 0) {
    Write-Host "Dependensi tidak bisa diimpor. Coba hapus .venv lalu jalankan ulang." -ForegroundColor Red
    exit $kode
}
$kode = Invoke-Uv "run", "python", "-m", "app.cli", "import-taxonomy"
if ($kode -ne 0) {
    Write-Host "Impor taksonomi gagal. Baca pesan di atas." -ForegroundColor Red
    exit $kode
}

Write-Host ""
if ((Get-Content ".env" -Raw) -match "(?m)^ADMIN_PASSWORD_HASH=\s*$") {
    Write-Host "Langkah wajib sebelum login:" -ForegroundColor Yellow
    Write-Host "  uv run python -m app.cli hash-password"
    Write-Host "  tempel hasilnya ke baris ADMIN_PASSWORD_HASH di .env, lalu jalankan ulang skrip ini"
    Write-Host ""
}

Write-Host "Selesai. Langkah berikutnya:" -ForegroundColor Green
Write-Host "  .\scripts\check.ps1     # lint dan tes"
Write-Host "  .\scripts\dev.ps1       # jalankan aplikasi di http://127.0.0.1:8000"
Write-Host "  buka http://127.0.0.1:8000/admin untuk panel admin"
