# Lint, cek format, dan tes. Gagal di langkah pertama yang bermasalah.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "ruff check" -ForegroundColor Cyan
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "ruff format --check" -ForegroundColor Cyan
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "pytest" -ForegroundColor Cyan
uv run pytest -q
exit $LASTEXITCODE
