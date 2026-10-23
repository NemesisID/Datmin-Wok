"""Klien OpenAlex: pencarian penulis, pengambilan karya, dan normalisasi.

Dipakai oleh spike Fase 0 dan nanti oleh OpenAlexProvider di Fase 2.
Tidak ada state global dan tidak ada I/O selain lewat httpx.Client yang diberikan.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_year",
        "publication_date",
        "cited_by_count",
        "abstract_inverted_index",
        "authorships",
        "primary_location",
        "type",
    ]
)


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Ubah abstract_inverted_index OpenAlex menjadi teks biasa."""
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions.append((index, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def normalize_work(raw: dict[str, Any]) -> dict[str, Any]:
    """Ambil hanya field yang dipakai aplikasi."""
    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    openalex_id = (raw.get("id") or "").rsplit("/", 1)[-1] or None
    author_ids = [
        ((authorship.get("author") or {}).get("id") or "").rsplit("/", 1)[-1]
        for authorship in raw.get("authorships") or []
    ]
    return {
        "openalex_id": openalex_id,
        "doi": raw.get("doi"),
        "title": (raw.get("display_name") or "").strip(),
        "year": raw.get("publication_year"),
        "venue": source.get("display_name"),
        "citations": raw.get("cited_by_count") or 0,
        "abstract": reconstruct_abstract(raw.get("abstract_inverted_index")),
        "type": raw.get("type"),
        "author_ids": [author_id for author_id in author_ids if author_id],
    }


def find_author_candidates(
    client: httpx.Client, name: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Cari kandidat penulis berdasarkan nama. Hasil mentah, belum disaring."""
    response = client.get(
        "/authors",
        params={
            "search": name,
            "per_page": limit,
            "select": "id,display_name,works_count,last_known_institutions,topics,summary_stats",
        },
    )
    response.raise_for_status()
    candidates = []
    for raw in response.json().get("results") or []:
        institutions = [
            item.get("display_name") for item in raw.get("last_known_institutions") or []
        ]
        topics = [item.get("display_name") for item in raw.get("topics") or []][:3]
        candidates.append(
            {
                "openalex_id": (raw.get("id") or "").rsplit("/", 1)[-1],
                "name": raw.get("display_name"),
                "works_count": raw.get("works_count"),
                "institutions": institutions,
                "topics": topics,
            }
        )
    return candidates


def fetch_author_works(
    client: httpx.Client,
    author_id: str,
    since: date,
    *,
    per_page: int = 100,
    max_pages: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ambil semua karya satu penulis sejak tanggal tertentu, halaman per halaman."""
    works: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "pages": 0,
        "total": None,
        "cost_usd": 0.0,
        "credits_used": [],
        "page_sizes": [],
    }
    for page in range(1, max_pages + 1):
        response = client.get(
            "/works",
            params={
                "filter": (
                    f"authorships.author.id:{author_id},from_publication_date:{since.isoformat()}"
                ),
                "select": SELECT_FIELDS,
                "sort": "publication_date:desc",
                "per_page": per_page,
                "page": page,
            },
        )
        response.raise_for_status()
        payload = response.json()
        body = payload.get("meta") or {}
        results = payload.get("results") or []

        meta["pages"] = page
        meta["total"] = body.get("count")
        meta["cost_usd"] += float(body.get("cost_usd") or body.get("cost") or 0)
        meta["credits_used"].append(response.headers.get("x-ratelimit-credits-used"))
        meta["page_sizes"].append(len(results))

        works.extend(normalize_work(item) for item in results)
        if len(results) < per_page:
            break
    return works, meta
