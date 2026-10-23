from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.providers.manual import ManualImportProvider
from app.providers.openalex import (
    OpenAlexProvider,
    build_client,
    fetch_author_works,
    lookup_work_by_title,
)


def make_client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.openalex.org",
        transport=httpx.MockTransport(handler),
    )


def make_work(index: int, year: int = 2024) -> dict:
    return {
        "id": f"https://openalex.org/W{index}",
        "doi": f"https://doi.org/10.1234/{index}",
        "display_name": f"Paper Nomor {index}",
        "publication_year": year,
        "cited_by_count": index,
        "abstract_inverted_index": {"halo": [0], "dunia": [1]},
        "authorships": [{"author": {"id": "https://openalex.org/A1"}}],
        "primary_location": {"source": {"display_name": "Jurnal Ilmiah"}},
    }


def test_fetch_author_works_pages_and_sends_bearer() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer kunci"
        page = int(request.url.params["page"])
        calls.append({"page": page, "filter": request.url.params["filter"]})
        results = [make_work(i) for i in range(100)] if page == 1 else [make_work(100)]
        return httpx.Response(
            200,
            json={
                "meta": {"count": 101, "cost_usd": 0.001},
                "results": results,
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(
        base_url="https://api.openalex.org",
        transport=transport,
        headers={"Authorization": "Bearer kunci"},
    ) as client:
        works, meta = fetch_author_works(client, "A1", date(2023, 1, 1))

    assert len(works) == 101
    assert meta["pages"] == 2
    assert meta["total"] == 101
    assert pytest.approx(meta["cost_usd"]) == 0.002
    assert "from_publication_date:2023-01-01" in calls[0]["filter"]
    assert works[0]["title"] == "Paper Nomor 0"
    assert works[0]["abstract"] == "halo dunia"


def test_fetch_author_works_retries_429_with_backoff() -> None:
    sleeps: list[float] = []
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"meta": {"count": 0, "cost_usd": 0}, "results": []})

    with make_client(handler) as client:
        works, meta = fetch_author_works(client, "A1", date(2023, 1, 1), sleep=sleeps.append)

    assert works == []
    assert meta["pages"] == 1
    assert sleeps == [1]
    assert attempts["count"] == 2


def test_provider_fetches_every_mapped_author_id() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        author_filter = request.url.params["filter"].split(",")[0]
        seen.append(author_filter)
        return httpx.Response(
            200,
            json={"meta": {"count": 1, "cost_usd": 0.01}, "results": [make_work(1)]},
        )

    with make_client(handler) as client:
        provider = OpenAlexProvider(client, sleep=lambda _seconds: None)
        result = provider.fetch(None, ["A1", "A2"], date(2023, 1, 1))

    assert len(result.papers) == 2
    assert result.requests == 2
    assert pytest.approx(result.credits) == 0.02
    assert seen == ["authorships.author.id:A1", "authorships.author.id:A2"]


def test_lookup_work_by_title_picks_best_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"cost_usd": 0.002},
                "results": [
                    {"display_name": "Topik Lain", "publication_year": 2024, "id": "W1"},
                    {
                        "display_name": "Sistem Informasi Manajemen Proyek",
                        "publication_year": 2024,
                        "id": "https://openalex.org/W2",
                        "doi": "https://doi.org/10.1/ok",
                        "cited_by_count": 7,
                        "abstract_inverted_index": {"abstrak": [0]},
                    },
                ],
            },
        )

    with make_client(handler) as client:
        work, cost = lookup_work_by_title(client, "Sistem Informasi Manajemen Proyek", 2024)

    assert work is not None
    assert work["id"].endswith("W2")
    assert pytest.approx(cost) == 0.002


def test_lookup_work_by_title_respects_year_window() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"cost_usd": 0},
                "results": [
                    {
                        "display_name": "Sistem Informasi Manajemen Proyek",
                        "publication_year": 2015,
                        "id": "W2",
                    }
                ],
            },
        )

    with make_client(handler) as client:
        work, _ = lookup_work_by_title(client, "Sistem Informasi Manajemen Proyek", 2024)

    assert work is None


def test_manual_csv_parses_and_filters_window() -> None:
    content = (
        b"Title,Year,Publication,Citations,DOI\n"
        b"Paper Baru,2024,Jurnal A,5,https://doi.org/10.1/x\n"
        b"Paper Lama,2019,Jurnal B,2,\n"
        b"Tanpa Tahun,,Jurnal C,1,\n"
    )
    provider = ManualImportProvider("ekspor.csv", content)
    result = provider.fetch(None, [], date(2023, 1, 1))

    assert [paper.title for paper in result.papers] == ["Paper Baru", "Tanpa Tahun"]
    assert result.papers[0].doi == "https://doi.org/10.1/x"
    assert result.papers[0].citations == 5
    assert result.papers[0].venue == "Jurnal A"


def test_manual_csv_accepts_indonesian_headers() -> None:
    content = b"Judul,Tahun,Jurnal,Sitasi\nSistem Informasi,2025,Jurnal SI,3\n"
    result = ManualImportProvider("ekspor.csv", content).fetch(None, [], date(2023, 1, 1))
    assert result.papers[0].title == "Sistem Informasi"
    assert result.papers[0].year == 2025


def test_manual_csv_without_title_column_is_rejected() -> None:
    provider = ManualImportProvider("ekspor.csv", b"Foo,Bar\n1,2\n")
    with pytest.raises(ValueError):
        provider.fetch(None, [], date(2023, 1, 1))


def test_manual_bibtex_parses_entries() -> None:
    content = b"""
    @article{satu,
      title = {Sistem {Informasi} Manajemen},
      year = {2024},
      journal = {Jurnal Ilmiah},
      doi = {10.1/y}
    }
    @inproceedings{dua,
      title = {Paper Lama},
      year = {2018},
      booktitle = {Seminar}
    }
    """
    result = ManualImportProvider("ekspor.bib", content).fetch(None, [], date(2023, 1, 1))

    assert len(result.papers) == 1
    assert result.papers[0].title == "Sistem Informasi Manajemen"
    assert result.papers[0].venue == "Jurnal Ilmiah"
    assert result.papers[0].year == 2024


def test_manual_import_enriches_missing_abstract_from_openalex() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"cost_usd": 0.001},
                "results": [
                    {
                        "display_name": "Sistem Informasi UMKM",
                        "publication_year": 2024,
                        "id": "https://openalex.org/W9",
                        "doi": "https://doi.org/10.1/umkm",
                        "cited_by_count": 12,
                        "abstract_inverted_index": {"abstrak": [0], "lengkap": [1]},
                    }
                ],
            },
        )

    content = b"Title,Year\nSistem Informasi UMKM,2024\n"
    with make_client(handler) as client:
        provider = ManualImportProvider(
            "ekspor.csv", content, client=client, sleep=lambda _seconds: None
        )
        result = provider.fetch(None, [], date(2023, 1, 1))

    paper = result.papers[0]
    assert paper.abstract == "abstrak lengkap"
    assert paper.doi == "https://doi.org/10.1/umkm"
    assert paper.openalex_id == "W9"
    assert paper.citations == 12
    assert "openalex" in paper.sources
    assert pytest.approx(result.credits) == 0.001
    assert result.requests == 1


def test_manual_import_rejects_unknown_extension() -> None:
    provider = ManualImportProvider("data.xlsx", b"x")
    with pytest.raises(ValueError):
        provider.fetch(None, [], date(2023, 1, 1))


def test_build_client_sets_bearer_header() -> None:
    client = build_client("https://api.openalex.org", "kunci")
    assert client.headers["Authorization"] == "Bearer kunci"
    client.close()
