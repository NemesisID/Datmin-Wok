from __future__ import annotations

from sqlmodel import Session, select

from app.dedupe import (
    compute_title_hash,
    find_match,
    merge_raw_into,
    normalize_doi,
    normalize_title,
    paper_from_raw,
    similarity,
    years_compatible,
)
from app.models import Paper
from app.providers.base import RawPaper


def test_normalize_title_strips_punctuation_and_stopwords() -> None:
    left = normalize_title("Analisis: Sistem Informasi untuk UMKM di Indonesia!")
    right = normalize_title("analisis sistem informasi umkm indonesia")
    assert left == right


def test_normalize_title_handles_unicode() -> None:
    assert normalize_title("Ｋｅｃｅｒｄａｓａｎ  Buatan") == "kecerdasan buatan"


def test_title_hash_is_stable() -> None:
    assert compute_title_hash("Judul Sama") == compute_title_hash("judul sama!")
    assert compute_title_hash("Judul Satu") != compute_title_hash("Judul Dua")


def test_normalize_doi_strips_prefixes() -> None:
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("doi:10.1234/abc") == "10.1234/abc"
    assert normalize_doi("  ") is None


def test_similarity_uses_token_sets() -> None:
    assert similarity("Sistem Informasi Manajemen", "Sistem Informasi Manajemen Proyek") > 0.99
    assert similarity("Jaringan Komputer", "Kecerdasan Buatan") < 0.5


def test_years_compatible_allows_one_year_gap_and_missing_year() -> None:
    assert years_compatible(2024, 2025)
    assert years_compatible(2024, None)
    assert not years_compatible(2024, 2026)


def test_exact_title_merges_within_one_year(session: Session) -> None:
    existing = paper_from_raw(RawPaper(title="Sistem Informasi UMKM", year=2024), "openalex")
    session.add(existing)
    session.commit()

    match = find_match(
        session,
        RawPaper(title="Sistem informasi UMKM!", year=2025, doi="10.1/x"),
    )
    assert match.paper is not None
    assert match.paper.id == existing.id
    assert match.candidate is None


def test_exact_title_different_year_is_new(session: Session) -> None:
    session.add(paper_from_raw(RawPaper(title="Sistem Informasi UMKM", year=2020), "openalex"))
    session.commit()

    match = find_match(session, RawPaper(title="Sistem Informasi UMKM", year=2025))
    assert match.paper is None


def test_doi_match_wins_over_different_title(session: Session) -> None:
    existing = paper_from_raw(
        RawPaper(title="Judul Versi Jurnal", year=2024, doi="https://doi.org/10.1/ABC"),
        "openalex",
    )
    session.add(existing)
    session.commit()

    match = find_match(
        session,
        RawPaper(title="Judul Versi Konferensi", year=2024, doi="10.1/abc"),
    )
    assert match.paper is not None
    assert match.paper.id == existing.id


def test_openalex_id_match_wins(session: Session) -> None:
    existing = paper_from_raw(
        RawPaper(title="Judul Lama", year=2024, openalex_id="W123"), "openalex"
    )
    session.add(existing)
    session.commit()

    match = find_match(session, RawPaper(title="Judul Baru", year=2024, openalex_id="W123"))
    assert match.paper is not None
    assert match.paper.id == existing.id


def test_fuzzy_title_same_year_goes_to_review_not_merge(session: Session) -> None:
    existing = paper_from_raw(
        RawPaper(title="Sistem Informasi Manajemen Proyek", year=2024), "openalex"
    )
    session.add(existing)
    session.commit()

    match = find_match(
        session,
        RawPaper(title="Sistem Informasi Manajemen Proyek di Indonesia", year=2024),
    )
    assert match.paper is None
    assert match.candidate is not None
    assert match.candidate.id == existing.id
    assert match.similarity >= 0.9


def test_fuzzy_title_different_year_is_not_a_candidate(session: Session) -> None:
    session.add(
        paper_from_raw(RawPaper(title="Sistem Informasi Manajemen Proyek", year=2020), "openalex")
    )
    session.commit()

    match = find_match(
        session,
        RawPaper(title="Sistem Informasi Manajemen Proyek di Indonesia", year=2024),
    )
    assert match.paper is None
    assert match.candidate is None


def test_merge_fills_empty_fields_and_keeps_higher_citations(session: Session) -> None:
    paper = paper_from_raw(
        RawPaper(title="Judul", year=2024, citations=2, sources=["openalex"]), "openalex"
    )
    session.add(paper)
    session.commit()

    changed = merge_raw_into(
        paper,
        RawPaper(
            title="Judul",
            year=2024,
            abstract="Abstrak",
            doi="10.1/abc",
            citations=9,
            scholar_pub_id="S1",
            sources=["manual"],
        ),
        "manual",
    )
    assert changed is True
    assert paper.abstract == "Abstrak"
    assert paper.doi_norm == "10.1/abc"
    assert paper.citations == 9
    assert paper.scholar_pub_id == "S1"
    assert paper.sources == ["manual", "openalex"]

    unchanged = merge_raw_into(
        paper, RawPaper(title="Judul", abstract="Baru", citations=1), "manual"
    )
    assert unchanged is False
    assert paper.abstract == "Abstrak"
    assert paper.citations == 9


def test_paper_from_raw_computes_title_hash_and_doi_norm() -> None:
    paper = paper_from_raw(
        RawPaper(title="Sistem Informasi", doi="https://doi.org/10.1/X", sources=["manual"]),
        "openalex",
    )
    assert paper.title_hash == compute_title_hash("Sistem Informasi")
    assert paper.doi_norm == "10.1/x"
    assert paper.sources == ["manual", "openalex"]


def test_no_duplicate_rows_created_on_merge(session: Session) -> None:
    session.add(paper_from_raw(RawPaper(title="Judul", year=2024), "openalex"))
    session.commit()

    paper = session.exec(select(Paper)).one()
    assert len(session.exec(select(Paper)).all()) == 1
    assert paper.title_hash == compute_title_hash("Judul")
