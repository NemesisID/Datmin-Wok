"""Aplikasi FastAPI: halaman publik, panel admin, dan health check."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.admin import router as admin_router
from app.config import get_settings
from app.public import router as public_router
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


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/admin"):
        if exc.status_code == 403:
            return render(request, "admin/403.html", status_code=403)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    messages = {
        400: "Permintaan tidak valid.",
        404: "Halaman tidak ditemukan.",
        405: "Metode tidak diizinkan.",
    }
    detail = messages.get(exc.status_code, "Terjadi kesalahan.")
    if exc.status_code == 400 and isinstance(exc.detail, str):
        detail = exc.detail
    if exc.status_code == 404 and isinstance(exc.detail, str) and exc.detail != "Not Found":
        detail = exc.detail
    return render(
        request,
        "public/error.html",
        status_code=exc.status_code,
        error=detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/admin"):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return render(
        request,
        "public/error.html",
        status_code=400,
        error="Permintaan tidak valid. Periksa filter atau alamat halaman.",
    )


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
app.include_router(public_router)


@app.get("/health")
def health() -> dict[str, object]:
    current = get_settings()
    return {
        "status": "ok",
        "phase": 5,
        "publication_window_years": current.publication_window_years,
    }
