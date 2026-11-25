"""Impor dosen dari CSV Perserikatan.

Kolom utama yang didukung: ``nama``, ``gelar``, ``scholar``, ``openalex_id``,
``aktif``, dan ``catatan``. Nama dibandingkan dengan normalisasi sehingga gelar
seperti ``Dr.`` atau ``S.Kom.`` tidak membuat duplikat.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import Lecturer, LecturerOpenAlexId
from app.person_names import lecturer_lookup, normalize_person_name
from app.security import normalize_openalex_id, parse_scholar_id

NAME_KEYS = ("nama", "nama dosen", "nama lengkap", "name", "dosen", "lecturer")
TITLE_KEYS = ("gelar", "gelar akademik", "gelar dosen", "title", "degree", "scholar title")
SCHOLAR_KEYS = (
    "url scholar",
    "url_scholar",
    "scholar url",
    "scholar",
    "google scholar",
    "id scholar",
)
OPENALEX_KEYS = (
    "openalex_id",
    "openalex id",
    "openalex",
    "id openalex",
    "openalex author",
    "openalex author id",
)
ACTIVE_KEYS = ("aktif", "active", "is active", "status")
NOTES_KEYS = ("catatan", "notes", "keterangan")

_TRUE_TOKENS = {"true", "1", "yes", "y", "ya", "aktif", "verifikasi"}
_FALSE_TOKENS = {"false", "0", "no", "n", "tidak", "tidak aktif"}
_PREFIX_RE = re.compile("^")


@dataclass
class LecturerImportRow:
    """Baris yang sudah dinormalisasi siap disimpan."""

    name: str
    title: str = ""
    scholar: str = ""
    openalex: str = ""
    active: str = ""
    notes: str = ""


@dataclass
class LecturerImportSummary:
    created: int = 0
    updated: int = 0
    openalex_added: int = 0
    rows: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower().replace("_", " ").replace("-", " ")).strip()


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str:
    normalized = {_normalize_header(key): value for key, value in row.items() if key}
    for key in keys:
        value = normalized.get(key)
        if value:
            return str(value).strip()
    return ""


def _parse_active(value: str, default: bool = True) -> bool:
    token = _normalize_header(value)
    if not token:
        return default
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return default


def parse_lecturer_csv(content: bytes) -> LecturerImportSummary:
    """Baca CSV sehingga menghasilkan daftar baris yang siap untuk disimpan."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV tidak punya baris judul kolom.")
    normalized_headers = {_normalize_header(header) for header in reader.fieldnames}
    if not any(header in NAME_KEYS for header in normalized_headers):
        raise ValueError("CSV harus punya kolom nama dosen, misalnya ``nama``.")

    rows: list[LecturerImportRow] = []
    errors: list[str] = []
    for position, raw in enumerate(reader, start=2):
        name = _pick(raw, NAME_KEYS)
        title = _pick(raw, TITLE_KEYS)
        scholar = _pick(raw, SCHOLAR_KEYS)
        openalex = _pick(raw, OPENALEX_KEYS)
        active_raw = _pick(raw, ACTIVE_KEYS)
        notes = _pick(raw, NOTES_KEYS)
        if not name:
            continue
        try:
            scholar_id = parse_scholar_id(scholar) if scholar else None
        except ValueError as error:
            errors.append(f"Baris {position}: {error}")
            continue
        try:
            openalex_id = normalize_openalex_id(openalex) if openalex else None
        except ValueError as error:
            errors.append(f"Baris {position}: {error}")
            continue
        rows.append(
            LecturerImportRow(
                name=name,
                title=title,
                scholar=scholar_id or "",
                openalex=openalex_id or "",
                active=active_raw,
                notes=notes,
            )
        )
    return LecturerImportSummary(rows=len(rows), errors=errors), rows


def import_lecturers(session: Session, content: bytes) -> LecturerImportSummary:
    """Impor dosen dari CSV tanpa menghapus data yang sudah ada.

    Aturan:
    - Baris dengan nama ternormalisasi dan Scholar ID yang sudah ada diperbarui.
    - Baris dengan nama ternormalisasi sama dianggap dosen yang sama.
    - ID OpenAlex hanya boleh dipakai satu dosen.
    - Baris error tidak menghentikan baris lain.
    """
    summary, rows = parse_lecturer_csv(content)
    existing = list(session.exec(select(Lecturer)).all())
    by_scholar = {row.scholar_id: row for row in existing if row.scholar_id}
    by_name = lecturer_lookup(session)

    for row in rows:
        existing_lecturer: Lecturer | None = None
        if row.scholar and row.scholar in by_scholar:
            existing_lecturer = by_scholar[row.scholar]
        else:
            normalized = normalize_person_name(row.name)
            if normalized and normalized in by_name:
                existing_lecturer = by_name[normalized]

        if existing_lecturer is not None:
            attach_openalex = False
            if row.openalex:
                openalex_owned = session.exec(
                    select(LecturerOpenAlexId).where(
                        LecturerOpenAlexId.openalex_author_id == row.openalex
                    )
                ).first()
                if openalex_owned is None:
                    attach_openalex = True
                elif openalex_owned.lecturer_id != existing_lecturer.id:
                    summary.errors.append(
                        f"Baris ``{row.name}``: ID OpenAlex {row.openalex} "
                        "sudah dipakai dosen lain."
                    )
                    continue
            duplicate_scholar = (
                row.scholar
                and existing_lecturer.scholar_id not in (None, row.scholar)
                and normalize_person_name(existing_lecturer.name) != normalize_person_name(row.name)
            )
            if duplicate_scholar:
                summary.errors.append(
                    f"Baris ``{row.name}``: ID Scholar sudah dipakai dosen lain "
                    f"({existing_lecturer.name})."
                )
                continue
            existing_lecturer.name = row.name
            existing_lecturer.title = row.title
            existing_lecturer.notes = row.notes
            existing_lecturer.active = _parse_active(row.active)
            if row.scholar and not existing_lecturer.scholar_id:
                existing_lecturer.scholar_id = row.scholar
                by_scholar[row.scholar] = existing_lecturer
            session.add(existing_lecturer)
            if attach_openalex:
                session.add(
                    LecturerOpenAlexId(
                        lecturer_id=existing_lecturer.id,
                        openalex_author_id=row.openalex,
                    )
                )
                summary.openalex_added += 1
            summary.updated += 1
        else:
            openalex_owned = None
            if row.openalex:
                openalex_owned = session.exec(
                    select(LecturerOpenAlexId).where(
                        LecturerOpenAlexId.openalex_author_id == row.openalex
                    )
                ).first()
                if openalex_owned is not None:
                    summary.errors.append(
                        f"Baris ``{row.name}``: ID OpenAlex {row.openalex} "
                        "sudah dipakai dosen lain."
                    )
                    continue
            active = _parse_active(row.active)
            notes = row.notes
            new_lecturer = Lecturer(
                name=row.name,
                title=row.title,
                scholar_id=row.scholar if row.scholar else None,
                active=active,
                notes=notes,
            )
            session.add(new_lecturer)
            session.flush()
            if row.openalex and new_lecturer.id is not None:
                session.add(
                    LecturerOpenAlexId(lecturer_id=new_lecturer.id, openalex_author_id=row.openalex)
                )
                summary.openalex_added += 1
            summary.created += 1
            if row.scholar:
                by_scholar[row.scholar] = new_lecturer
            by_name[normalize_person_name(row.name)] = new_lecturer
    if summary.created or summary.updated or summary.openalex_added:
        session.commit()
    return summary
