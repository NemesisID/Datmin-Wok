"""Aplikasi FastAPI: halaman publik dasar dan panel admin."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin import router as admin_router
from app.config import get_settings
from app.templating import render

ROOT = Path(__file__).resolve().parents[1]

settings = get_settings()
if not settings.secret_key:
    logging.warning(
        "SECRET_KEY kosong. Sesi admin memakai kunci acak dan hilang saat server restart."
    )
session_secret = settings.secret_key or secrets.token_urlsafe(32)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 403 and request.url.path.startswith("/admin"):
        return render(request, "admin/403.html", status_code=403)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.middleware("http")
async def admin_guard(request: Request, call_next):
    path = request.url.path
    if (
        (path == "/admin" or path.startswith("/admin/"))
        and path != "/admin/login"
        and not request.session.get("admin")
    ):
        return RedirectResponse("/admin/login", status_code=303)
    return await call_next(request)


# SessionMiddleware didaftarkan terakhir supaya membungkus admin_guard,
# sehingga request.session sudah tersedia di middleware dan di rute.
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="sesi",
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.cookie_secure,
)

app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, object]:
    current = get_settings()
    return {
        "status": "ok",
        "phase": 3,
        "publication_window_years": current.publication_window_years,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rekomendasi Pembimbing Skripsi</title>
  <link rel="stylesheet" href="/static/admin.css">
</head>
<body>
  <main class="sempit">
    <h1>Rekomendasi Pembimbing Skripsi</h1>
    <p>Halaman pencarian untuk mahasiswa dibangun di Fase 5. Saat ini data dosen dan
    taksonomi dikelola lewat panel admin.</p>
    <p><a class="tombol" href="/admin">Masuk panel admin</a></p>
  </main>
</body>
</html>"""
