"""Aplikasi web Fase 0: kerangka yang bisa dijalankan dan diuji."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import get_settings

app = FastAPI(title=get_settings().app_name)


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "phase": 0,
        "publication_window_years": settings.publication_window_years,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rekomendasi Pembimbing Skripsi</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;
           line-height: 1.6; color: #1a1a1a; background: #fff; }
    code { background: #f2f2f2; padding: 0.1rem 0.3rem; border-radius: 3px; }
  </style>
</head>
<body>
  <h1>Rekomendasi Pembimbing Skripsi</h1>
  <p>Fase 0 selesai: aplikasi berjalan. Halaman pencarian dibangun di Fase 5.</p>
  <p>Status: <code>GET /health</code></p>
</body>
</html>"""
