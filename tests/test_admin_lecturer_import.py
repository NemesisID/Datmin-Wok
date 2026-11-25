from __future__ import annotations

import csv
import io

from conftest import csrf_from, login
from sqlmodel import Session, select

from app.models import Lecturer, LecturerOpenAlexId


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    text = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row})
    writer = csv.DictWriter(text, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def _upload(client, content: bytes):
    page = client.get("/admin/dosen/impor")
    token = csrf_from(page)
    return client.post(
        "/admin/dosen/impor",
        data={"csrf_token": token},
        files={"file": ("dosen.csv", content, "text/csv")},
        follow_redirects=False,
    )


def test_import_lecturers_csv(client, engine) -> None:
    login(client)
    content = _csv_bytes(
        [
            {"nama": "Dosen Satu", "gelar": "S.Kom., M.Kom.", "aktif": "true"},
            {"nama": "Dosen Dua", "gelar": "S.T.", "aktif": "false"},
            {"nama": "Dosen Tiga", "url_scholar": "XXXXXXXXXXXX", "aktif": "0"},
        ]
    )
    response = _upload(client, content)
    assert response.status_code == 303

    with Session(engine) as session:
        lecturers = session.exec(select(Lecturer)).all()
        names = {row.name for row in lecturers}
    assert names == {"Dosen Satu", "Dosen Dua", "Dosen Tiga"}


def test_import_update_existing_lecturer(client, engine) -> None:
    login(client)
    content = _csv_bytes(
        [
            {"nama": "Dosen Satu", "gelar": "S.Kom., M.Kom.", "aktif": "true"},
        ]
    )
    _upload(client, content)
    content = _csv_bytes(
        [
            {"nama": "Dr. Dosen Satu, S.Kom., M.Kom.", "aktif": "false"},
        ]
    )
    _upload(client, content)

    with Session(engine) as session:
        lecturers = session.exec(select(Lecturer)).all()
        assert len(lecturers) == 1
        lecturer = lecturers[0]
        assert lecturer.name == "Dr. Dosen Satu, S.Kom., M.Kom."
        assert lecturer.active is False


def test_import_openalex_is_assigned(client, engine) -> None:
    login(client)
    content = _csv_bytes(
        [
            {"nama": "Dosen Satu", "openalex_id": "A5056916903", "aktif": "true"},
        ]
    )
    _upload(client, content)

    with Session(engine) as session:
        mapping = session.exec(select(LecturerOpenAlexId)).one()
    assert mapping.openalex_author_id == "A5056916903"


def test_import_rejects_wrong_openalex(client, engine) -> None:
    login(client)
    content = _csv_bytes(
        [
            {"nama": "Dosen Satu", "openalex_id": "bukan-id", "aktif": "true"},
        ]
    )
    _upload(client, content)

    with Session(engine) as session:
        assert session.exec(select(Lecturer)).first() is None


def test_import_requires_name_header(client, engine) -> None:
    login(client)
    content = _csv_bytes(
        [
            {"gelar": "S.Kom., M.Kom."},
        ]
    )
    response = _upload(client, content)
    assert response.status_code == 303
    page = client.get("/admin/dosen")
    assert "CSV harus punya kolom nama dosen" in page.text
    with Session(engine) as session:
        assert session.exec(select(Lecturer)).first() is None


def test_import_adds_openalex_to_existing_lecturer(client, engine) -> None:
    login(client)
    _upload(client, _csv_bytes([{"nama": "Dosen Satu", "aktif": "true"}]))
    _upload(
        client,
        _csv_bytes([{"nama": "Dr. Dosen Satu", "openalex_id": "A5056916903", "aktif": "true"}]),
    )

    with Session(engine) as session:
        mapping = session.exec(select(LecturerOpenAlexId)).one()
    assert mapping.openalex_author_id == "A5056916903"
