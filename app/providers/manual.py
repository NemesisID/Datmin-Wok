"""Impor publikasi dari ekspor CSV atau BibTeX Google Scholar."""

from __future__ import annotations

import csv
import io
import re
import time
from datetime import date

import bibtexparser

from app.providers.base import ProviderResult, RawPaper
from app.providers.openalex import lookup_work_by_title, reconstruct_abstract

TITLE_KEYS = ("title", "judul", "paper", "nama paper", "article title")
YEAR_KEYS = ("year", "tahun", "publication year")
VENUE_KEYS = ("venue", "journal", "jurnal", "publication", "sumber", "publisher")
DOI_KEYS = ("doi",)
CITATION_KEYS = ("citations", "cited by", "sitasi", "citation", "cited")
SCHOLAR_ID_KEYS = ("id", "pub id", "scholar id", "publication id")

YEAR_RE = re.compile(r"(19|20)\d{2}")


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().replace("_", " ").replace("-", " ")).strip()


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str:
    normalized = {_normalize_header(key): value for key, value in row.items() if key}
    for key in keys:
        value = normalized.get(key)
        if value:
            return str(value).strip()
    return ""


def _parse_year(value: str) -> int | None:
    match = YEAR_RE.search(value or "")
    return int(match.group(0)) if match else None


def _parse_int(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else 0


def _clean_bibtex(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("{", "").replace("}", "")).strip()


class ManualImportProvider:
    name = "manual"

    def __init__(
        self,
        filename: str,
        content: bytes,
        *,
        client=None,
        sleep=time.sleep,
    ) -> None:
        self.filename = filename
        self.content = content
        self.client = client
        self.sleep = sleep
        self.credits = 0.0
        self.requests = 0

    def fetch(self, lecturer, openalex_ids: list[str], since: date):
        papers = self._parse()
        papers = [paper for paper in papers if paper.year is None or paper.year >= since.year]
        if self.client is not None:
            for paper in papers:
                self._enrich(paper)
        return ProviderResult(papers=papers, credits=self.credits, requests=self.requests)

    def _parse(self) -> list[RawPaper]:
        name = self.filename.lower()
        if name.endswith(".bib") or name.endswith(".bibtex"):
            return self._parse_bibtex()
        if name.endswith(".csv"):
            return self._parse_csv()
        raise ValueError("Berkas harus .csv, .bib, atau .bibtex.")

    def _parse_csv(self) -> list[RawPaper]:
        text = self.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV tidak punya baris judul kolom.")
        if not any(_normalize_header(header) in TITLE_KEYS for header in reader.fieldnames):
            raise ValueError("CSV tidak punya kolom judul (title atau judul).")

        papers = []
        for row in reader:
            title = _pick(row, TITLE_KEYS)
            if not title:
                continue
            papers.append(
                RawPaper(
                    title=title,
                    year=_parse_year(_pick(row, YEAR_KEYS)),
                    venue=_pick(row, VENUE_KEYS),
                    doi=_pick(row, DOI_KEYS) or None,
                    citations=_parse_int(_pick(row, CITATION_KEYS)),
                    scholar_pub_id=_pick(row, SCHOLAR_ID_KEYS) or None,
                    sources=["manual"],
                )
            )
        return papers

    def _parse_bibtex(self) -> list[RawPaper]:
        text = self.content.decode("utf-8-sig", errors="replace")
        try:
            library = bibtexparser.loads(text)
        except Exception as error:  # bibtexparser melempar tipe berbeda-beda
            raise ValueError(f"BibTeX tidak bisa diparse: {error}") from error

        papers = []
        for entry in library.entries:
            title = _clean_bibtex(entry.get("title", ""))
            if not title:
                continue
            venue = _clean_bibtex(entry.get("journal") or entry.get("booktitle") or "")
            papers.append(
                RawPaper(
                    title=title,
                    year=_parse_year(entry.get("year", "")),
                    venue=venue,
                    doi=(entry.get("doi") or "").strip() or None,
                    sources=["manual"],
                )
            )
        return papers

    def _enrich(self, paper: RawPaper) -> None:
        if paper.abstract and paper.doi:
            return
        work, cost = lookup_work_by_title(self.client, paper.title, paper.year, sleep=self.sleep)
        self.credits += cost
        self.requests += 1
        if work is None:
            return
        if not paper.abstract:
            paper.abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        if not paper.doi:
            paper.doi = work.get("doi")
        if not paper.openalex_id:
            paper.openalex_id = (work.get("id") or "").rsplit("/", 1)[-1] or None
        paper.citations = max(paper.citations, work.get("cited_by_count") or 0)
        if "openalex" not in paper.sources:
            paper.sources.append("openalex")
