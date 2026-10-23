"""Antarmuka sumber publikasi dan bentuk data mentah yang seragam."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.models import Lecturer


@dataclass(slots=True)
class RawPaper:
    title: str
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    openalex_id: str | None = None
    scholar_pub_id: str | None = None
    abstract: str | None = None
    citations: int = 0
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderResult:
    papers: list[RawPaper] = field(default_factory=list)
    credits: float = 0.0
    requests: int = 0


class PublicationProvider(Protocol):
    name: str

    def fetch(self, lecturer: Lecturer, openalex_ids: list[str], since: date) -> ProviderResult: ...
