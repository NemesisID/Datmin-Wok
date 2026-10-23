from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.public_data import (
    add_lecturer,
    add_paper,
    add_thesis,
    seed_public,
    set_last_sync,
)


def _seed_result(session: Session):
    topics = seed_public(session)
    mining = topics["Data Mining"]
    first = add_lecturer(session, "Dosen Satu")
    second = add_lecturer(session, "Dosen Dua")
    add_paper(
        session,
        first,
        "Sistem Informasi Manajemen Proyek",
        year=2025,
        labels=[(mining, 0.95, None)],
    )
    add_paper(
        session,
        second,
        "Klasifikasi Data Mining",
        year=2024,
        labels=[(mining, 0.9, None)],
    )
    return topics, first, second


def test_empty_state_is_rendered(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Belum ada data" in response.text
    assert "admin belum menyinkronkan" in response.text.lower()


def test_ranked_search_shows_rank_and_evidence(client: TestClient, session: Session) -> None:
    topics, first, _ = _seed_result(session)
    response = client.get(f"/?topik={topics['Data Mining'].id}")
    assert response.status_code == 200
    assert "Peringkat 1" in response.text
    assert first.name in response.text
    assert "Sistem Informasi Manajemen Proyek" in response.text
    assert "data-score" not in response.text
    assert "skor" not in response.text.lower()


def test_browse_lab_without_evidence_shows_empty_message(
    client: TestClient, session: Session
) -> None:
    topics = seed_public(session)
    lecturer = add_lecturer(session, "Dosen Solusi")
    add_paper(
        session,
        lecturer,
        "Paper Data Mining",
        labels=[(topics["Data Mining"], 0.9, None)],
    )
    response = client.get("/?lab=MSI")
    assert response.status_code == 200
    assert "Tidak ada dosen dengan bukti di filter ini" in response.text


def test_browse_counts_one_paper_once_across_topics(client: TestClient, session: Session) -> None:
    topics = seed_public(session)
    lecturer = add_lecturer(session, "Dosen Multi Topik")
    add_paper(
        session,
        lecturer,
        "Paper Lintas Topik",
        labels=[
            (topics["Data Mining"], 0.9, None),
            (topics["UI/UX"], 0.8, None),
        ],
    )
    response = client.get("/")
    assert response.status_code == 200
    assert "1 bukti relevan" in response.text


def test_zero_result_state_suggests_loosening_filters(client: TestClient, session: Session) -> None:
    _seed_result(session)
    response = client.get("/?q=kata-yang-tidak-ada")
    assert response.status_code == 200
    assert "Tidak ada dosen yang cocok" in response.text
    assert "Longgarkan" in response.text


def test_stale_state_is_visible(client: TestClient, session: Session) -> None:
    topics, first, _ = _seed_result(session)
    set_last_sync(first, session, days_ago=100)
    response = client.get(f"/?topik={topics['Data Mining'].id}")
    assert response.status_code == 200
    assert "lebih dari 90 hari" in response.text


def test_lecturer_detail_hides_student_identity(client: TestClient, session: Session) -> None:
    topics = seed_public(session)
    lecturer = add_lecturer(session, "Dosen Profil")
    add_thesis(
        session,
        lecturer,
        "Judul Skripsi Rahasia",
        student_name="Nama Mahasiswa Rahasia",
        nim="NIM-RAHASIA-123",
        labels=[(topics["Data Mining"], 0.9)],
    )
    response = client.get(f"/dosen/{lecturer.id}")
    assert response.status_code == 200
    assert "Judul Skripsi Rahasia" in response.text
    assert "Nama Mahasiswa Rahasia" not in response.text
    assert "NIM-RAHASIA-123" not in response.text


def test_detail_paper_filter_uses_topic(client: TestClient, session: Session) -> None:
    topics = seed_public(session)
    lecturer = add_lecturer(session, "Dosen Filter Profil")
    add_paper(
        session,
        lecturer,
        "Paper Data Mining",
        year=2025,
        labels=[(topics["Data Mining"], 0.9, None)],
    )
    add_paper(
        session,
        lecturer,
        "Paper UI UX",
        year=2025,
        labels=[(topics["UI/UX"], 0.9, None)],
    )
    response = client.get(f"/dosen/{lecturer.id}?topik={topics['Data Mining'].id}")
    assert response.status_code == 200
    assert "Paper Data Mining" in response.text
    assert "Paper UI UX" not in response.text


def test_compare_accepts_two_and_rejects_more_than_three(
    client: TestClient, session: Session
) -> None:
    seed_public(session)
    lecturers = [add_lecturer(session, f"Dosen {index}") for index in range(4)]
    ids = [lecturer.id for lecturer in lecturers]
    one = client.get(f"/bandingkan?dosen={ids[0]}")
    assert one.status_code == 400
    assert "setidaknya dua" in one.text
    ok = client.get(f"/bandingkan?dosen={ids[0]}&dosen={ids[1]}")
    assert ok.status_code == 200
    assert "Bandingkan dosen" in ok.text
    too_many = "&".join(f"dosen={item}" for item in ids)
    rejected = client.get(f"/bandingkan?{too_many}")
    assert rejected.status_code == 400
    assert "Maksimal 3 dosen" in rejected.text


def test_unknown_lecturer_and_invalid_year_use_error_page(
    client: TestClient, session: Session
) -> None:
    seed_public(session)
    missing = client.get("/dosen/99999")
    assert missing.status_code == 404
    assert "Dosen tidak ditemukan" in missing.text
    invalid = client.get("/?tahun_dari=2030")
    assert invalid.status_code == 400
    assert "Rentang tahun" in invalid.text


def test_topic_explorer_and_lecturer_list(client: TestClient, session: Session) -> None:
    topics, first, _ = _seed_result(session)
    topics_response = client.get("/topik")
    assert topics_response.status_code == 200
    assert "Data Mining" in topics_response.text
    assert first.name in topics_response.text

    list_response = client.get("/dosen")
    assert list_response.status_code == 200
    assert first.name in list_response.text
    assert "Sistem Informasi Manajemen Proyek" not in list_response.text


def test_filter_options_and_public_css_are_linked(client: TestClient, session: Session) -> None:
    topics = seed_public(session)
    response = client.get("/")
    assert 'name="topik"' in response.text
    assert topics["Data Mining"].name in response.text
    assert "/static/public.css" in response.text
    assert 'name="viewport"' in response.text


def test_invalid_topic_filter_is_rejected(client: TestClient, session: Session) -> None:
    seed_public(session)
    response = client.get("/?topik=99999")
    assert response.status_code == 400
    assert "Topik yang dipilih tidak aktif" in response.text


@pytest.mark.parametrize("path", ["/", "/dosen", "/topik"])
def test_public_pages_respond(client: TestClient, session: Session, path: str) -> None:
    seed_public(session)
    add_lecturer(session, "Dosen Halaman")
    response = client.get(path)
    assert response.status_code == 200
    assert "Terjadi kesalahan" not in response.text
