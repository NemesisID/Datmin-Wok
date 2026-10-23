from __future__ import annotations

import csv
import io

from sqlmodel import Session, select

from app.models import ImportBatch, LecturerAlias, Thesis
from tests.conftest import csrf_from, login
from tests.factories import make_lecturer, make_thesis

HEADERS = [
    "Judul",
    "Pembimbing 1",
    "Pembimbing 2",
    "Nama",
    "NIM",
    "Tahun",
    "Topik",
]
MAPPING = {
    "judul": 0,
    "pembimbing1": 1,
    "pembimbing2": 2,
    "nama": 3,
    "nim": 4,
    "tahun": 5,
    "topik": 6,
}


def csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows([HEADERS, *rows])
    return buffer.getvalue().encode("utf-8")


def upload(client, content: bytes, filename: str = "skripsi.csv"):
    page = client.get("/admin/skripsi")
    return client.post(
        "/admin/skripsi/unggah",
        data={"csrf_token": csrf_from(page)},
        files={"file": (filename, content, "text/csv")},
        follow_redirects=False,
    )


def map_batch(client, batch_id: int):
    page = client.get(f"/admin/skripsi/{batch_id}/petakan")
    assert page.status_code == 200
    data = {f"map_{key}": str(index) for key, index in MAPPING.items()}
    data["csrf_token"] = csrf_from(page)
    return client.post(
        f"/admin/skripsi/{batch_id}/petakan",
        data=data,
        follow_redirects=False,
    )


def confirm(client, batch_id: int):
    page = client.get(f"/admin/skripsi/{batch_id}")
    return client.post(
        f"/admin/skripsi/{batch_id}/konfirmasi",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )


def preview_batch(client, content: bytes) -> int:
    response = upload(client, content)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.endswith("/petakan")
    batch_id = int(location.split("/")[-2])
    response = map_batch(client, batch_id)
    assert response.status_code == 303, response.text
    return batch_id


def test_upload_map_confirm_and_rollback(client, engine) -> None:
    with Session(engine) as session:
        make_lecturer(session, "Dosen Satu")
    login(client)

    page = client.get("/admin/skripsi")
    assert page.status_code == 200
    assert "Impor skripsi lama" in page.text

    content = csv_bytes(
        [
            [
                "Sistem Informasi Manajemen Proyek",
                "Dosen Satu, M.Kom.",
                "",
                "Ani",
                "123",
                "2024",
                "",
            ]
        ]
    )
    response = upload(client, content)
    assert response.status_code == 303
    location = response.headers["location"]
    batch_id = int(location.split("/")[-2])

    mapping_page = client.get(location)
    assert mapping_page.status_code == 200
    assert "Sistem Informasi Manajemen Proyek" in mapping_page.text
    assert map_batch(client, batch_id).status_code == 303

    detail = client.get(f"/admin/skripsi/{batch_id}")
    assert detail.status_code == 200
    assert "Pratinjau" in detail.text
    assert "Sistem Informasi Manajemen Proyek" in detail.text

    response = confirm(client, batch_id)
    assert response.status_code == 303
    with Session(engine) as session:
        assert len(session.exec(select(Thesis)).all()) == 1

    detail = client.get(f"/admin/skripsi/{batch_id}")
    assert "Batch sudah dikonfirmasi" in detail.text

    response = client.post(
        f"/admin/skripsi/{batch_id}/rollback",
        data={"csrf_token": csrf_from(detail)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with Session(engine) as session:
        assert session.exec(select(Thesis)).all() == []


def test_review_row_can_be_kept_from_browser(client, engine) -> None:
    with Session(engine) as session:
        lecturer = make_lecturer(session, "Dosen Satu")
        make_thesis(
            session,
            "Sistem Informasi Manajemen Proyek",
            year=2020,
            supervisors=[lecturer],
        )
    login(client)
    batch_id = preview_batch(
        client,
        csv_bytes(
            [
                [
                    "Sistem Informasi Manajemen Proyek",
                    "Dosen Satu, M.Kom.",
                    "",
                    "Ani",
                    "123",
                    "2024",
                    "",
                ]
            ]
        ),
    )

    detail = client.get(f"/admin/skripsi/{batch_id}")
    assert "perlu review" in detail.text

    response = client.post(
        f"/admin/skripsi/{batch_id}/konfirmasi",
        data={"csrf_token": csrf_from(detail)},
        follow_redirects=True,
    )
    assert "perlu diputuskan" in response.text

    with Session(engine) as session:
        from app.models import ImportRow

        row = session.exec(select(ImportRow).where(ImportRow.batch_id == batch_id)).one()
        row_id = row.id

    assert (
        client.post(
            f"/admin/skripsi/{batch_id}/baris/{row_id}",
            data={"csrf_token": csrf_from(detail), "keputusan": "keep"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert confirm(client, batch_id).status_code == 303
    with Session(engine) as session:
        assert len(session.exec(select(Thesis)).all()) == 2


def test_unknown_supervisor_can_be_mapped_from_browser(client, engine) -> None:
    with Session(engine) as session:
        lecturer = make_lecturer(session, "Dosen Baru")
    login(client)
    batch_id = preview_batch(
        client,
        csv_bytes(
            [
                [
                    "Sistem Informasi Manajemen Proyek",
                    "Dosen Misterius, M.Kom.",
                    "",
                    "Ani",
                    "123",
                    "2024",
                    "",
                ]
            ]
        ),
    )

    detail = client.get(f"/admin/skripsi/{batch_id}")
    assert "Pembimbing tak dikenal" in detail.text
    assert "Dosen Misterius, M.Kom." in detail.text

    response = client.post(
        f"/admin/skripsi/{batch_id}/alias",
        data={
            "csrf_token": csrf_from(detail),
            "nama": "Dosen Misterius, M.Kom.",
            "dosen_id": str(lecturer.id),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    client.get(f"/admin/skripsi/{batch_id}")
    detail = client.get(f"/admin/skripsi/{batch_id}")
    assert "Dosen Misterius, M.Kom." not in detail.text
    assert confirm(client, batch_id).status_code == 303
    with Session(engine) as session:
        assert len(session.exec(select(Thesis)).all()) == 1
        alias = session.exec(select(LecturerAlias)).one()
        assert alias.lecturer_id == lecturer.id


def test_upload_rejects_wrong_extension(client, engine) -> None:
    login(client)
    response = upload(client, b"bukan skripsi", filename="data.txt")
    assert response.status_code == 303
    page = client.get("/admin/skripsi")
    assert "harus .csv atau .xlsx" in page.text
    with Session(engine) as session:
        assert session.exec(select(ImportBatch)).all() == []


def test_upload_rejects_broken_csv(client, engine) -> None:
    login(client)
    response = upload(client, b"Judul\nSistem A\n")
    assert response.status_code == 303
    page = client.get("/admin/skripsi")
    assert "dua kolom" in page.text
    with Session(engine) as session:
        assert session.exec(select(ImportBatch)).all() == []
