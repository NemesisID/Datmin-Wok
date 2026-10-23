"""Klien OpenAlex: pencarian penulis, pengambilan karya, dan normalisasi."""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

from app.dedupe import similarity
from app.providers.base import ProviderResult, RawPaper

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

TITLE_SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_year",
        "cited_by_count",
        "abstract_inverted_index",
    ]
)

RETRY_STATUSES = {429, 500, 502, 503, 504}


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


def raw_from_work(work: dict[str, Any]) -> RawPaper:
    return RawPaper(
        title=work["title"],
        year=work.get("year"),
        venue=work.get("venue") or "",
        doi=work.get("doi"),
        openalex_id=work.get("openalex_id"),
        abstract=work.get("abstract"),
        citations=work.get("citations") or 0,
        sources=["openalex"],
    )


def _request(
    client: httpx.Client,
    path: str,
    params: dict[str, Any],
    sleep,
    attempts: int = 4,
) -> httpx.Response:
    for attempt in range(attempts):
        response = client.get(path, params=params)
        if response.status_code in RETRY_STATUSES and attempt < attempts - 1:
            sleep(2**attempt)
            continue
        response.raise_for_status()
        return response
    raise RuntimeError("Permintaan OpenAlex gagal setelah beberapa percobaan.")


def find_author_candidates(
    client: httpx.Client, name: str, limit: int = 10, sleep=time.sleep
) -> list[dict[str, Any]]:
    """Cari kandidat penulis berdasarkan nama. Hasil mentah, belum disaring."""
    response = _request(
        client,
        "/authors",
        {
            "search": name,
            "per_page": limit,
            "select": "id,display_name,works_count,last_known_institutions,topics,summary_stats",
        },
        sleep,
    )
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
    sleep=time.sleep,
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
        response = _request(
            client,
            "/works",
            {
                "filter": (
                    f"authorships.author.id:{author_id},from_publication_date:{since.isoformat()}"
                ),
                "select": SELECT_FIELDS,
                "sort": "publication_date:desc",
                "per_page": per_page,
                "page": page,
            },
            sleep,
        )
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


def lookup_work_by_title(
    client: httpx.Client,
    title: str,
    year: int | None = None,
    sleep=time.sleep,
) -> tuple[dict[str, Any] | None, float]:
    """Cari satu karya OpenAlex yang judulnya cocok. Untuk melengkapi impor manual."""
    if not title.strip():
        return None, 0.0
    safe_title = title.replace(",", " ").replace("|", " ").strip()
    response = _request(
        client,
        "/works",
        {
            "filter": f"title.search:{safe_title}",
            "select": TITLE_SELECT_FIELDS,
            "per_page": 5,
        },
        sleep,
    )
    payload = response.json()
    cost = float((payload.get("meta") or {}).get("cost_usd") or 0)
    best: dict[str, Any] | None = None
    best_score = 0.0
    for raw in payload.get("results") or []:
        found_year = raw.get("publication_year")
        if year is not None and found_year is not None and abs(found_year - year) > 1:
            continue
        score = similarity(title, raw.get("display_name") or "")
        if score > best_score:
            best, best_score = raw, score
    if best is None or best_score < 0.90:
        return None, cost
    return best, cost


def build_client(base_url: str, api_key: str = "", timeout: float = 30.0) -> httpx.Client:
    headers = {"User-Agent": "rekomendasi-pembimbing/0.2"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=timeout)


class OpenAlexProvider:
    name = "openalex"

    def __init__(
        self,
        client: httpx.Client,
        *,
        per_page: int = 100,
        max_pages: int = 20,
        sleep=time.sleep,
    ) -> None:
        self.client = client
        self.per_page = per_page
        self.max_pages = max_pages
        self.sleep = sleep

    def fetch(self, lecturer, openalex_ids: list[str], since: date) -> ProviderResult:
        result = ProviderResult()
        for index, author_id in enumerate(openalex_ids):
            works, meta = fetch_author_works(
                self.client,
                author_id,
                since,
                per_page=self.per_page,
                max_pages=self.max_pages,
                sleep=self.sleep,
            )
            result.credits += meta["cost_usd"]
            result.requests += meta["pages"]
            result.papers.extend(raw_from_work(work) for work in works)
            if index < len(openalex_ids) - 1:
                self.sleep(0.2)
        return result
