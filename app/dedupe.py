"""Deduplikasi berbasis judul. Abstrak tidak pernah dibandingkan."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlmodel import Session, select

from app.models import Paper, utcnow
from app.providers.base import RawPaper

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "dan",
        "dengan",
        "dari",
        "di",
        "for",
        "in",
        "into",
        "is",
        "ke",
        "oleh",
        "on",
        "atau",
        "pada",
        "sebagai",
        "the",
        "to",
        "untuk",
        "yang",
    ]
)
NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:")


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").lower()
    text = NON_WORD_RE.sub(" ", text).replace("_", " ")
    words = [word for word in SPACE_RE.sub(" ", text).split() if word not in STOPWORDS]
    return " ".join(words)


def compute_title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def normalize_doi(doi: str | None) -> str | None:
    value = (doi or "").strip().lower()
    for prefix in DOI_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip()
    return value or None


def similarity(left: str, right: str) -> float:
    return fuzz.token_set_ratio(normalize_title(left), normalize_title(right)) / 100


def years_compatible(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return True
    return abs(left - right) <= 1


@dataclass
class MatchResult:
    paper: Paper | None = None
    candidate: Paper | None = None
    similarity: float = 0.0

    @property
    def needs_review(self) -> bool:
        return self.paper is None and self.candidate is not None


def find_match(session: Session, incoming: RawPaper) -> MatchResult:
    doi = normalize_doi(incoming.doi)
    if doi:
        found = session.exec(select(Paper).where(Paper.doi_norm == doi)).first()
        if found:
            return MatchResult(paper=found)
    if incoming.openalex_id:
        found = session.exec(select(Paper).where(Paper.openalex_id == incoming.openalex_id)).first()
        if found:
            return MatchResult(paper=found)
    if incoming.scholar_pub_id:
        found = session.exec(
            select(Paper).where(Paper.scholar_pub_id == incoming.scholar_pub_id)
        ).first()
        if found:
            return MatchResult(paper=found)

    normalized = normalize_title(incoming.title)
    if not normalized:
        return MatchResult()

    title_hash = compute_title_hash(incoming.title)
    for row in session.exec(select(Paper).where(Paper.title_hash == title_hash)).all():
        if years_compatible(row.year, incoming.year):
            return MatchResult(paper=row)

    if incoming.year is not None:
        same_year = session.exec(select(Paper).where(Paper.year == incoming.year)).all()
        best: Paper | None = None
        best_score = 0.0
        for row in same_year:
            score = similarity(row.title, incoming.title)
            if score >= 0.90 and score > best_score:
                best, best_score = row, score
        if best is not None:
            return MatchResult(candidate=best, similarity=best_score)

    return MatchResult()


def paper_from_raw(raw: RawPaper, source: str) -> Paper:
    return Paper(
        title=raw.title.strip(),
        title_hash=compute_title_hash(raw.title),
        year=raw.year,
        venue=raw.venue or "",
        doi=raw.doi,
        doi_norm=normalize_doi(raw.doi),
        abstract=raw.abstract,
        citations=raw.citations or 0,
        scholar_pub_id=raw.scholar_pub_id,
        openalex_id=raw.openalex_id,
        sources=sorted({*(raw.sources or []), source}),
    )


def merge_raw_into(target: Paper, raw: RawPaper, source: str) -> bool:
    """Isi field yang masih kosong dan ambil sitasi tertinggi. Tidak menimpa data kuat."""
    changed = False
    if not target.abstract and raw.abstract:
        target.abstract = raw.abstract
        changed = True
    if not target.venue and raw.venue:
        target.venue = raw.venue
        changed = True
    if not target.doi and raw.doi:
        target.doi = raw.doi
        target.doi_norm = normalize_doi(raw.doi)
        changed = True
    if not target.openalex_id and raw.openalex_id:
        target.openalex_id = raw.openalex_id
        changed = True
    if not target.scholar_pub_id and raw.scholar_pub_id:
        target.scholar_pub_id = raw.scholar_pub_id
        changed = True
    if (raw.citations or 0) > (target.citations or 0):
        target.citations = raw.citations
        changed = True
    sources = sorted({*(target.sources or []), *(raw.sources or []), source})
    if sources != list(target.sources or []):
        target.sources = sources
        changed = True
    if changed:
        target.updated_at = utcnow()
    return changed


def merge_paper_into(target: Paper, source: Paper) -> None:
    """Gabungkan dua baris paper yang sudah ada. Target yang dipertahankan."""
    incoming = RawPaper(
        title=source.title,
        year=source.year,
        venue=source.venue,
        doi=source.doi,
        openalex_id=source.openalex_id,
        scholar_pub_id=source.scholar_pub_id,
        abstract=source.abstract,
        citations=source.citations,
        sources=list(source.sources or []),
    )
    merge_raw_into(target, incoming, "merge")
