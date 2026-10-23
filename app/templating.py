"""Lokasi template, render dengan konteks umum, dan pesan sekali tampil."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def render(request: Request, name: str, *, status_code: int = 200, **context: Any):
    context.setdefault("app_name", get_settings().app_name)
    context["csrf_token"] = request.session.get("csrf", "")
    context["admin"] = request.session.get("admin")
    context["flash"] = request.session.pop("_flash", [])
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, message: str) -> None:
    request.session.setdefault("_flash", []).append(message)
