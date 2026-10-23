from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from app.recommend import (
    SearchFilters,
    evidence_label,
    lecturer_profile,
    recency,
    recommend,
    shrink,
    topic_explorer,
)
from tests.public_data import add_lecturer, add_paper, add_thesis, seed_public


def test_recency_and_shrinkage_follow_prd() -> None:
    assert recency(2024, 2026, 2) == pytest.approx(0.5)
    assert recency(2023, 2026, 2) == pytest.approx(0.5**1.5)
    assert recency(None, 2026, 2) == 1.0
    assert shrink(3.2) == pytest.approx(3.2 / 5.2)
    assert shrink(0) == 0


def test_evidence_labels_use_boundaries() -> None:
    assert evidence_label(0.1999) == "Lemah"
    assert evidence_label(0.20) == "Cukup"
    assert evidence_label(0.45) == "Cukup"
    assert evidence_label(0.4501) == "Kuat"


def test_ranked_results_and_no_data_group(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    strong = add_lecturer(session, "Dosen Kuat")
    enough = add_lecturer(session, "Dosen Cukup")
    empty = add_lecturer(session, "Dosen Kosong")
    add_paper(
        session,
        strong,
        "Data Mining Klasifikasi",
        year=2025,
        labels=[(mining, 0.9, None)],
    )
    add_paper(
        session,
        strong,
        "Clustering Data",
        year=2024,
        labels=[(mining, 0.8, None)],
    )
    add_paper(
        session,
        enough,
        "Klasifikasi Sederhana",
        year=2025,
        labels=[(mining, 0.8, None)],
    )

    result = recommend(
        session,
        SearchFilters(topic_ids=(mining.id,), current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )

    assert [item.lecturer.name for item in result.results] == ["Dosen Kuat", "Dosen Cukup"]
    assert [item.rank for item in result.results] == [1, 2]
    assert [item.lecturer.name for item in result.no_data] == [empty.name]
    assert result.results[0].label == "Cukup"
    assert result.has_criteria is True


def test_multi_topic_coverage_changes_order(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    uiux = topics["UI/UX"]
    broad = add_lecturer(session, "Dosen Luas")
    narrow = add_lecturer(session, "Dosen Sempit")
    add_paper(session, broad, "Data Mining", labels=[(mining, 0.9, None)])
    add_paper(session, broad, "User Experience", labels=[(uiux, 0.9, None)])
    add_paper(session, narrow, "Data Mining Dua", labels=[(mining, 0.9, None)])
    add_paper(session, narrow, "Data Mining Tiga", labels=[(mining, 0.9, None)])

    result = recommend(
        session,
        SearchFilters(topic_ids=(mining.id, uiux.id), current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert result.results[0].lecturer.name == "Dosen Luas"
    assert any(item.topic.id == uiux.id for item in result.results[0].topics)


def test_thesis_evidence_is_lambda_weighted(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    lecturer = add_lecturer(session, "Dosen Bimbing")
    add_thesis(
        session,
        lecturer,
        "Skripsi Data Mining",
        labels=[(mining, 1.0)],
    )
    result = recommend(
        session,
        SearchFilters(topic_ids=(mining.id,), current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert result.results[0].theses
    assert result.results[0].label == "Cukup"
    assert result.results[0].theses[0].thesis.title == "Skripsi Data Mining"


def test_filters_limit_papers_by_year_and_subtopic(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    sentiment = topics["Analisis Sentimen"]
    lecturer = add_lecturer(session, "Dosen Filter")
    add_paper(
        session,
        lecturer,
        "Paper Lama",
        year=2020,
        labels=[(mining, 0.9, sentiment.id)],
    )
    add_paper(
        session,
        lecturer,
        "Paper Baru",
        year=2025,
        labels=[(mining, 0.9, sentiment.id)],
    )
    add_paper(
        session,
        lecturer,
        "Paper Umum",
        year=2025,
        labels=[(mining, 0.9, None)],
    )

    filtered = recommend(
        session,
        SearchFilters(
            topic_ids=(mining.id,),
            subtopic_ids=(sentiment.id,),
            year_from=2024,
            current_year=2026,
        ),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    papers = filtered.results[0].papers
    assert [item.paper.title for item in papers] == ["Paper Baru"]


def test_fts_title_route_finds_lecturer_without_labels(session: Session) -> None:
    seed_public(session)
    lecturer = add_lecturer(session, "Dosen Judul")
    add_paper(session, lecturer, "Sistem Informasi Manajemen Proyek", year=2024)

    result = recommend(
        session,
        SearchFilters(query="manajemen proyek", current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert result.results[0].lecturer.name == "Dosen Judul"
    assert result.results[0].papers[0].direct is True
    assert result.results[0].papers[0].paper.title == "Sistem Informasi Manajemen Proyek"


def test_query_classifier_adds_topic_evidence(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    lecturer = add_lecturer(session, "Dosen Sentimen")
    add_paper(
        session,
        lecturer,
        "Penelitian Teks",
        year=2025,
        labels=[(mining, 0.8, None)],
    )

    result = recommend(
        session,
        SearchFilters(query="data mining klasifikasi", current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert result.query_topics
    assert result.results[0].lecturer.name == "Dosen Sentimen"


def test_lab_filter_and_topic_explorer(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    uiux = topics["UI/UX"]
    lecturer = add_lecturer(session, "Dosen Lab")
    add_paper(session, lecturer, "Paper Mining", labels=[(mining, 0.9, None)])
    add_paper(session, lecturer, "Paper UI", labels=[(uiux, 0.9, None)])

    result = recommend(
        session,
        SearchFilters(lab="MSI", current_year=2026),
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert [item.lecturer.name for item in result.all_lecturers if item.has_data] == ["Dosen Lab"]

    explorer = topic_explorer(session, lab="MSI", now=datetime(2026, 10, 23, tzinfo=UTC))
    assert "MSI" in explorer.groups
    entries = {entry.topic.name: entry for entry in explorer.groups["MSI"]}
    assert entries["UI/UX"].lecturers[0].lecturer.name == "Dosen Lab"


def test_profile_hides_identity_through_data_shape(session: Session) -> None:
    topics = seed_public(session)
    mining = topics["Data Mining"]
    lecturer = add_lecturer(session, "Dosen Profil")
    add_thesis(
        session,
        lecturer,
        "Skripsi Rahasia",
        student_name="Nama Mahasiswa",
        nim="NIM-123",
        labels=[(mining, 0.9)],
    )
    profile = lecturer_profile(
        session,
        lecturer.id,
        now=datetime(2026, 10, 23, tzinfo=UTC),
    )
    assert profile is not None
    assert profile.theses[0].thesis.title == "Skripsi Rahasia"
    assert not hasattr(profile.theses[0], "student_name")
    assert profile.topics_by_lab["SOLUSI"][0].topic.name == "Data Mining"
