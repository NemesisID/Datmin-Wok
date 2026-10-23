from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from openpyxl import Workbook
from sqlmodel import Session, select

from app.models import (
    ImportBatch,
    ImportRow,
    LecturerAlias,
    Thesis,
    ThesisSupervisor,
    ThesisTopic,
    utcnow,
)
from app.thesis_import import (
    add_alias,
    apply_mapping,
    cleanup_expired_batches,
    confirm_batch,
    create_batch,
    detect_mapping,
    normalize_nim,
    parse_upload,
    rollback_batch,
    set_row_decision,
    summary_of,
    validate_mapping,
)
from tests.factories import make_lecturer, make_thesis, seed_minimal_taxonomy

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


def csv_bytes(rows: list[list[str]], delimiter: str = ",") -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def xlsx_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def data_row(
    title: str,
    supervisor: str = "Dosen Satu, M.Kom.",
    *,
    year: str = "2024",
    nim: str = "",
    second: str = "",
    topic: str = "",
) -> list[str]:
    return [title, supervisor, second, "Mahasiswa", nim, year, topic]


def preview(
    session: Session, rows: list[list[str]], *, filename: str = "skripsi.csv"
) -> ImportBatch:
    batch = create_batch(session, filename, csv_bytes([HEADERS, *rows]))
    apply_mapping(session, batch, MAPPING)
    session.refresh(batch)
    return batch


def first_row(session: Session, batch: ImportBatch) -> ImportRow:
    row = session.exec(
        select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_number)
    ).first()
    assert row is not None
    return row


def test_parse_csv_and_xlsx() -> None:
    parsed = parse_upload(
        "data.csv",
        "\ufeffJudul;Pembimbing 1;Tahun\nSistem A;Dosen A;2024\n".encode("utf-8"),
    )
    assert parsed.headers == ["Judul", "Pembimbing 1", "Tahun"]
    assert parsed.rows[0].row_number == 2
    assert parsed.rows[0].values == ["Sistem A", "Dosen A", "2024"]

    content = xlsx_bytes([[], ["Judul", "Pembimbing 1", "Tahun"], ["Sistem B", "Dosen B", 2023]])
    parsed = parse_upload("data.xlsx", content)
    assert parsed.headers == ["Judul", "Pembimbing 1", "Tahun"]
    assert parsed.rows[0].row_number == 3
    assert parsed.rows[0].values == ["Sistem B", "Dosen B", "2023"]

    with pytest.raises(ValueError):
        parse_upload("data.txt", b"apa saja")
    with pytest.raises(ValueError):
        parse_upload("data.csv", b"")


def test_parse_rejects_single_column_and_empty_data() -> None:
    with pytest.raises(ValueError, match="dua kolom"):
        parse_upload("data.csv", b"Judul\nSistem A\n")
    with pytest.raises(ValueError, match="baris data"):
        parse_upload("data.csv", b"Judul,Pembimbing\n")


def test_detect_mapping_headers() -> None:
    mapping = detect_mapping(
        [
            "Judul Skripsi",
            "Nama Pembimbing 1",
            "Pembimbing II",
            "Nama Mahasiswa",
            "NIM",
            "Tahun Lulus",
            "Topik",
        ]
    )
    assert mapping == MAPPING

    english = detect_mapping(
        [
            "Title",
            "First Supervisor",
            "Second Supervisor",
            "Student Name",
            "Student ID",
            "Year",
            "Topic",
        ]
    )
    assert english == MAPPING


def test_validate_mapping_rejects_missing_and_duplicate_columns() -> None:
    headers = ["Judul", "Pembimbing 1"]
    with pytest.raises(ValueError, match="judul"):
        validate_mapping(headers, {"pembimbing1": 1})
    with pytest.raises(ValueError, match="dipakai"):
        validate_mapping(headers, {"judul": 0, "pembimbing1": 0})


def test_normalize_nim_handles_common_excel_forms() -> None:
    assert normalize_nim("12.345.678") == "12345678"
    assert normalize_nim("12345678.0") == "12345678"
    assert normalize_nim("1.2345678E+7") == "12345678"
    assert normalize_nim("NIM 123 456") == "nim123456"


def test_preview_does_not_insert_until_confirmed(session: Session) -> None:
    seed_minimal_taxonomy(session)
    lecturer = make_lecturer(session, "Dosen Satu")
    make_lecturer(session, "Dosen Dua")
    batch = preview(
        session,
        [
            data_row(
                "Sistem Informasi Manajemen Proyek",
                "Dosen Satu, M.Kom.",
                second="Dosen Dua, M.T.",
                topic="Data Mining",
            )
        ],
    )
    summary = summary_of(batch)
    assert summary["new"] == 1
    assert summary["unknown"] == 0
    assert session.exec(select(Thesis)).all() == []

    result = confirm_batch(session, batch)
    assert result["inserted"] == 1
    thesis = session.exec(select(Thesis)).one()
    assert thesis.import_batch_id == batch.id
    assert thesis.student_name == "Mahasiswa"
    supervisors = session.exec(
        select(ThesisSupervisor).where(ThesisSupervisor.thesis_id == thesis.id)
    ).all()
    assert {link.lecturer_id for link in supervisors} == {lecturer.id, 2}
    labels = session.exec(select(ThesisTopic).where(ThesisTopic.thesis_id == thesis.id)).all()
    assert [(label.topic_id, label.source, label.locked) for label in labels] == [
        (1, "import", True)
    ]
    assert batch.status == "committed"
    with pytest.raises(ValueError):
        confirm_batch(session, batch)


def test_imported_topic_maps_subtopic_to_parent_and_multiple(session: Session) -> None:
    seed_minimal_taxonomy(session)
    make_lecturer(session, "Dosen Satu")
    batch = preview(
        session,
        [data_row("Judul Netral Tanpa Kata Kunci", topic="Analisis Sentimen; UI/UX")],
    )
    assert summary_of(batch)["new"] == 1
    confirm_batch(session, batch)
    thesis = session.exec(select(Thesis)).one()
    labels = session.exec(select(ThesisTopic).where(ThesisTopic.thesis_id == thesis.id)).all()
    assert {(label.topic_id, label.source, label.locked) for label in labels} == {
        (1, "import", True),
        (2, "import", True),
    }


def test_exact_duplicates_by_title_year_and_nim(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    make_thesis(
        session,
        "Sistem Informasi Manajemen Proyek",
        year=2024,
        nim="111",
    )
    batch = preview(
        session,
        [
            data_row("Sistem Informasi Manajemen Proyek", "Dosen Satu, M.Kom.", nim="999"),
            data_row("Aplikasi Penjualan", "Dosen Satu, M.Kom.", nim="111"),
            data_row("Judul Baru", "Dosen Satu, M.Kom.", nim="222", year="2025"),
        ],
    )
    summary = summary_of(batch)
    assert summary["exact"] == 2
    assert summary["new"] == 1

    result = confirm_batch(session, batch)
    assert result["inserted"] == 1
    theses = session.exec(select(Thesis)).all()
    assert len(theses) == 2
    inserted = session.exec(select(Thesis).where(Thesis.nim == "222")).one()
    supervisors = session.exec(
        select(ThesisSupervisor).where(ThesisSupervisor.thesis_id == inserted.id)
    ).all()
    assert [link.lecturer_id for link in supervisors] == [lecturer.id]


def test_same_title_different_cohort_needs_review(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    make_thesis(
        session,
        "Sistem Informasi Manajemen Proyek",
        year=2020,
        supervisors=[lecturer],
    )
    batch = preview(
        session,
        [data_row("Sistem Informasi Manajemen Proyek", "Dosen Satu, M.Kom.", year="2024")],
    )
    assert summary_of(batch)["review"] == 1
    with pytest.raises(ValueError, match="perlu diputuskan"):
        confirm_batch(session, batch)

    row = first_row(session, batch)
    set_row_decision(session, batch, row, "skip")
    result = confirm_batch(session, batch)
    assert result["inserted"] == 0


def test_in_file_duplicate_inserts_only_one(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    batch = preview(
        session,
        [
            data_row("Sistem Informasi Manajemen Proyek", "Dosen Satu, M.Kom."),
            data_row("Sistem Informasi Manajemen Proyek", "Dosen Satu, M.Kom."),
        ],
    )
    summary = summary_of(batch)
    assert summary["new"] == 1
    assert summary["exact"] == 1
    result = confirm_batch(session, batch)
    assert result["inserted"] == 1
    thesis = session.exec(select(Thesis)).one()
    supervisors = session.exec(
        select(ThesisSupervisor).where(ThesisSupervisor.thesis_id == thesis.id)
    ).all()
    assert [link.lecturer_id for link in supervisors] == [lecturer.id]


def test_similar_title_above_90_is_skipped(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    make_thesis(
        session,
        "Perancangan Sistem Informasi Manajemen Proyek Berbasis Web",
        year=2024,
        supervisors=[lecturer],
    )
    batch = preview(
        session,
        [
            data_row(
                "Sistem Informasi Manajemen Proyek Berbasis Website",
                "Dosen Satu, M.Kom.",
                year="2023",
            )
        ],
    )
    summary = summary_of(batch)
    assert summary["similar"] == 1
    assert summary["new"] == 0
    result = confirm_batch(session, batch)
    assert result["inserted"] == 0


def test_similar_title_80_to_90_needs_review(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    make_thesis(
        session,
        "Perancangan Sistem Informasi Manajemen Proyek Berbasis Web",
        year=2024,
        supervisors=[lecturer],
    )
    batch = preview(
        session,
        [
            data_row(
                "Sistem Informasi Manajemen Proyek Konstruksi",
                "Dosen Satu, M.Kom.",
                year="2023",
            )
        ],
    )
    assert summary_of(batch)["review"] == 1
    row = first_row(session, batch)
    set_row_decision(session, batch, row, "keep")
    result = confirm_batch(session, batch)
    assert result["inserted"] == 1


def test_similar_title_needs_overlapping_supervisor(session: Session) -> None:
    supervisor_a = make_lecturer(session, "Dosen Satu")
    make_lecturer(session, "Dosen Dua")
    make_thesis(
        session,
        "Perancangan Sistem Informasi Manajemen Proyek Berbasis Web",
        year=2024,
        supervisors=[supervisor_a],
    )
    batch = preview(
        session,
        [
            data_row(
                "Sistem Informasi Manajemen Proyek Berbasis Website",
                "Dosen Dua, M.Kom.",
                year="2023",
            )
        ],
    )
    summary = summary_of(batch)
    assert summary["new"] == 1
    assert summary["similar"] == 0
    assert confirm_batch(session, batch)["inserted"] == 1


def test_unknown_supervisor_alias_and_rollback(session: Session) -> None:
    make_lecturer(session, "Dosen Satu")
    new_lecturer = make_lecturer(session, "Dosen Baru")
    batch = preview(
        session,
        [data_row("Sistem Informasi Manajemen Proyek", "Dosen Tak Dikenal, M.Kom.")],
    )
    summary = summary_of(batch)
    assert summary["unknown"] == 1
    assert summary["unknown_names"] == ["Dosen Tak Dikenal, M.Kom."]
    with pytest.raises(ValueError, match="tak dikenal"):
        confirm_batch(session, batch)

    raw_name = "Dosen Tak Dikenal, M.Kom."
    add_alias(session, batch, raw_name, new_lecturer.id)
    session.refresh(batch)
    summary = summary_of(batch)
    assert summary["unknown"] == 0
    assert summary["new"] == 1
    alias = session.exec(select(LecturerAlias)).one()
    assert alias.created_by_batch_id == batch.id

    assert confirm_batch(session, batch)["inserted"] == 1
    thesis = session.exec(select(Thesis)).one()
    supervisors = session.exec(
        select(ThesisSupervisor).where(ThesisSupervisor.thesis_id == thesis.id)
    ).all()
    assert [link.lecturer_id for link in supervisors] == [new_lecturer.id]

    manual = make_thesis(session, "Skripsi Manual yang Tetap Ada", year=2025)
    removed = rollback_batch(session, batch)
    assert removed == 1
    remaining = session.exec(select(Thesis)).all()
    assert [item.id for item in remaining] == [manual.id]
    assert session.exec(select(LecturerAlias)).all() == []
    assert session.get(ImportBatch, batch.id).status == "rolled_back"
    row = first_row(session, batch)
    assert row.thesis_id is None
    assert summary_of(session.get(ImportBatch, batch.id))["inserted"] == 0


def test_double_upload_yields_zero_new(session: Session) -> None:
    make_lecturer(session, "Dosen Satu")
    rows = [data_row("Sistem Informasi Manajemen Proyek")]
    first = preview(session, rows)
    confirm_batch(session, first)
    assert len(session.exec(select(Thesis)).all()) == 1

    second = preview(session, rows)
    summary = summary_of(second)
    assert summary["exact"] == 1
    assert summary["new"] == 0
    assert confirm_batch(session, second)["inserted"] == 0
    assert len(session.exec(select(Thesis)).all()) == 1


def test_expired_preview_cleanup_removes_rows_and_alias(session: Session) -> None:
    make_lecturer(session, "Dosen Satu")
    lecturer = make_lecturer(session, "Dosen Baru")
    batch = preview(
        session,
        [data_row("Sistem Informasi Manajemen Proyek", "Dosen Asing, M.Kom.")],
    )
    add_alias(session, batch, "Dosen Asing, M.Kom.", lecturer.id)
    batch.created_at = utcnow() - timedelta(hours=25)
    session.add(batch)
    session.commit()

    assert cleanup_expired_batches(session) == 1
    assert session.get(ImportBatch, batch.id) is None
    assert session.exec(select(ImportRow)).all() == []
    assert session.exec(select(LecturerAlias)).all() == []


def test_confirm_rolls_back_on_classification_error(session: Session, monkeypatch) -> None:
    make_lecturer(session, "Dosen Satu")
    batch = preview(session, [data_row("Sistem Informasi Manajemen Proyek")])

    def explode(*args, **kwargs):
        raise RuntimeError("klasifikasi gagal")

    monkeypatch.setattr("app.thesis_import.reclassify_theses", explode)
    with pytest.raises(RuntimeError, match="klasifikasi gagal"):
        confirm_batch(session, batch)

    session.expire_all()
    assert session.exec(select(Thesis)).all() == []
    assert session.exec(select(ThesisSupervisor)).all() == []
    stored = session.get(ImportBatch, batch.id)
    assert stored is not None
    assert stored.status == "preview"
    assert first_row(session, stored).thesis_id is None


def test_invalid_rows_do_not_block_confirmation(session: Session) -> None:
    make_lecturer(session, "Dosen Satu")
    batch = preview(
        session,
        [
            data_row("", "Dosen Satu, M.Kom."),
            data_row("Judul Tanpa Pembimbing", ""),
            data_row("Judul dengan Gelar Saja", "S.Kom."),
        ],
    )
    summary = summary_of(batch)
    assert summary["invalid"] == 3
    result = confirm_batch(session, batch)
    assert result["inserted"] == 0
    assert session.exec(select(Thesis)).all() == []
    assert batch.status == "committed"
