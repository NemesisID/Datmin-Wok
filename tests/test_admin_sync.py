from __future__ import annotations

from conftest import csrf_from, login
from sqlmodel import Session, select

from app.models import (
    Lecturer,
    LecturerOpenAlexId,
    LecturerPaper,
    Paper,
    PaperDuplicate,
    SyncJob,
    utcnow,
)


def seed_lecturer(engine, name: str = "Dosen Uji", *, with_openalex: bool = True) -> int:
    with Session(engine) as session:
        lecturer = Lecturer(name=name, active=True)
        session.add(lecturer)
        session.commit()
        session.refresh(lecturer)
        if with_openalex:
            session.add(
                LecturerOpenAlexId(lecturer_id=lecturer.id, openalex_author_id="A5000000001")
            )
            session.commit()
        return lecturer.id


def upload(client, lecturer_id: int, filename: str, content: bytes):
    page = client.get(f"/admin/dosen/{lecturer_id}/impor")
    return client.post(
        f"/admin/dosen/{lecturer_id}/impor",
        data={"csrf_token": csrf_from(page)},
        files={"file": (filename, content, "text/csv")},
        follow_redirects=False,
    )


def test_sync_button_enqueues_job_without_running_it(client, engine) -> None:
    login(client)
    lecturer_id = seed_lecturer(engine)

    page = client.get(f"/admin/dosen/{lecturer_id}")
    response = client.post(
        f"/admin/dosen/{lecturer_id}/sinkronkan",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        job = session.exec(select(SyncJob)).one()
    assert job.status == "pending"
    assert job.source == "openalex"


def test_sync_button_requires_openalex_mapping(client, engine) -> None:
    login(client)
    lecturer_id = seed_lecturer(engine, with_openalex=False)

    page = client.get(f"/admin/dosen/{lecturer_id}")
    response = client.post(
        f"/admin/dosen/{lecturer_id}/sinkronkan",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        assert session.exec(select(SyncJob)).first() is None


def test_csv_import_adds_papers_and_is_idempotent(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)
    content = (
        b"Title,Year,Publication,Citations,DOI\n"
        b"Sistem Informasi Manajemen Proyek,2024,Jurnal SI,4,10.1/abc\n"
        b"Kecerdasan Buatan untuk UMKM,2025,Jurnal AI,2,\n"
    )

    response = upload(client, lecturer_id, "ekspor.csv", content)
    assert response.status_code == 303

    with Session(engine) as session:
        assert len(session.exec(select(Paper)).all()) == 2
        assert len(session.exec(select(LecturerPaper)).all()) == 2
        job = session.exec(select(SyncJob)).one()
        assert job.status == "done"
        assert job.source == "manual"
        assert job.new_papers == 2
        assert job.credits_used == 0

    response = upload(client, lecturer_id, "ekspor.csv", content)
    assert response.status_code == 303

    with Session(engine) as session:
        assert len(session.exec(select(Paper)).all()) == 2
        jobs = session.exec(select(SyncJob).order_by(SyncJob.id)).all()
        assert jobs[-1].new_papers == 0


def test_import_rejects_wrong_extension(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)

    response = upload(client, lecturer_id, "data.txt", b"bukan csv")
    assert response.status_code == 303

    with Session(engine) as session:
        assert session.exec(select(Paper)).first() is None
        assert session.exec(select(SyncJob)).first() is None


def test_import_rejects_broken_csv(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)

    response = upload(client, lecturer_id, "rusak.csv", b"Foo,Bar\n1,2\n")
    assert response.status_code == 303

    with Session(engine) as session:
        job = session.exec(select(SyncJob)).one()
    assert job.status == "failed"
    assert "judul" in job.error


def test_lecturer_page_lists_imported_papers(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)
    content = b"Title,Year\nSistem Informasi Manajemen Proyek,2024\n"
    upload(client, lecturer_id, "ekspor.csv", content)

    page = client.get(f"/admin/dosen/{lecturer_id}")
    assert page.status_code == 200
    assert "Sistem Informasi Manajemen Proyek" in page.text
    assert "Sinkronkan sekarang" in page.text
    assert "selesai" in page.text


def test_duplicate_queue_can_merge(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)
    content = (
        b"Title,Year\n"
        b"Sistem Informasi Manajemen Proyek,2024\n"
        b"Sistem Informasi Manajemen Proyek di Indonesia,2024\n"
    )
    upload(client, lecturer_id, "ekspor.csv", content)

    with Session(engine) as session:
        duplicate = session.exec(select(PaperDuplicate)).one()
        assert duplicate.status == "pending"

    page = client.get("/admin/duplikat")
    assert page.status_code == 200
    assert "Kemiripan" in page.text

    duplicate_id = duplicate.id
    response = client.post(
        f"/admin/duplikat/{duplicate_id}/gabung",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        assert len(session.exec(select(Paper)).all()) == 1
        assert len(session.exec(select(LecturerPaper)).all()) == 1
        assert session.exec(select(PaperDuplicate)).first() is None

    assert "Tidak ada kandidat" in client.get("/admin/duplikat").text


def test_duplicate_queue_can_keep_both(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)
    content = (
        b"Title,Year\n"
        b"Sistem Informasi Manajemen Proyek,2024\n"
        b"Sistem Informasi Manajemen Proyek di Indonesia,2024\n"
    )
    upload(client, lecturer_id, "ekspor.csv", content)

    with Session(engine) as session:
        duplicate_id = session.exec(select(PaperDuplicate)).one().id

    page = client.get("/admin/duplikat")
    response = client.post(
        f"/admin/duplikat/{duplicate_id}/biarkan",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(engine) as session:
        assert session.get(PaperDuplicate, duplicate_id).status == "kept"
        assert len(session.exec(select(Paper)).all()) == 2


def test_duplicate_merge_is_visible_on_dashboard(client, engine) -> None:
    login(client)
    with Session(engine) as session:
        first = Paper(title="Satu", title_hash="a", year=2024)
        second = Paper(title="Dua", title_hash="b", year=2024)
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)
        session.add(
            PaperDuplicate(
                paper_id=second.id,
                candidate_id=first.id,
                similarity=0.95,
                status="pending",
            )
        )
        session.commit()

    page = client.get("/admin")
    assert "Duplikat" in page.text
    assert "1" in page.text


def test_jobs_have_timestamps_and_credits(client, engine, monkeypatch) -> None:
    monkeypatch.setattr("app.admin.build_client", lambda *args, **kwargs: None)
    login(client)
    lecturer_id = seed_lecturer(engine)
    upload(client, lecturer_id, "ekspor.csv", b"Title,Year\nPaper,2024\n")

    with Session(engine) as session:
        job = session.exec(select(SyncJob)).one()
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.finished_at >= job.started_at
        assert utcnow().tzinfo is not None
