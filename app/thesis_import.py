"""Impor data skripsi lama: baca berkas, cek duplikat, pratinjau, dan konfirmasi."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from openpyxl import load_workbook
from sqlmodel import Session, select

from app.classify import reclassify_theses
from app.dedupe import compute_title_hash, normalize_title, similarity
from app.models import (
    ImportBatch,
    ImportRow,
    Lecturer,
    LecturerAlias,
    Thesis,
    ThesisSupervisor,
    ThesisTopic,
    Topic,
    utcnow,
)
from app.person_names import lecturer_lookup, normalize_person_name
from app.taxonomy import get_taxonomy_version, normalize_keyword

PREVIEW_TTL = timedelta(hours=24)
SUPPORTED_SUFFIXES = (".csv", ".xlsx")
YEAR_RE = re.compile(r"(19|20)\d{2}")
TOPIC_SPLIT_RE = re.compile(r"[;,]")


@dataclass(frozen=True)
class MappingField:
    key: str
    label: str
    required: bool
    synonyms: tuple[str, ...]


MAPPING_FIELDS: tuple[MappingField, ...] = (
    MappingField(
        "judul",
        "Judul skripsi",
        True,
        ("judul", "judul skripsi", "title", "title of thesis", "thesis title"),
    ),
    MappingField(
        "pembimbing1",
        "Pembimbing 1",
        True,
        (
            "pembimbing 1",
            "pembimbing1",
            "pembimbing i",
            "pembimbing utama",
            "pembimbing skripsi 1",
            "nama pembimbing 1",
            "nama pembimbing i",
            "dosen pembimbing 1",
            "dosen pembimbing i",
            "nama dosen pembimbing 1",
            "supervisor 1",
            "supervisor i",
            "first supervisor",
        ),
    ),
    MappingField(
        "pembimbing2",
        "Pembimbing 2",
        False,
        (
            "pembimbing 2",
            "pembimbing2",
            "pembimbing ii",
            "pembimbing pendamping",
            "pembimbing skripsi 2",
            "nama pembimbing 2",
            "nama pembimbing ii",
            "dosen pembimbing 2",
            "dosen pembimbing ii",
            "nama dosen pembimbing 2",
            "supervisor 2",
            "supervisor ii",
            "second supervisor",
        ),
    ),
    MappingField(
        "nama",
        "Nama mahasiswa",
        False,
        ("nama", "nama mahasiswa", "mahasiswa", "student", "student name", "nama siswa"),
    ),
    MappingField(
        "nim",
        "NIM",
        False,
        (
            "nim",
            "n i m",
            "nomor induk mahasiswa",
            "nomor pokok mahasiswa",
            "npm",
            "student id",
            "student number",
        ),
    ),
    MappingField(
        "tahun",
        "Tahun",
        False,
        ("tahun", "tahun lulus", "tahun skripsi", "tahun wisuda", "angkatan", "year"),
    ),
    MappingField(
        "topik",
        "Topik (opsional)",
        False,
        (
            "topik",
            "topik skripsi",
            "bidang",
            "bidang minat",
            "bidang keahlian",
            "topic",
            "topic area",
        ),
    ),
)

MAPPING_BY_KEY = {item.key: item for item in MAPPING_FIELDS}


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    values: list[str]


@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[ParsedRow]


@dataclass(frozen=True)
class ThesisCandidate:
    title: str
    title_hash: str
    year: int | None
    nim_norm: str
    supervisor_ids: frozenset[int]
    thesis_id: int | None = None
    row_number: int | None = None


@dataclass
class CandidateIndex:
    by_hash: dict[str, list[ThesisCandidate]] = field(default_factory=lambda: defaultdict(list))
    by_nim: dict[str, list[ThesisCandidate]] = field(default_factory=lambda: defaultdict(list))
    by_supervisor_year: dict[tuple[int, int], list[ThesisCandidate]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    def from_session(cls, session: Session) -> CandidateIndex:
        index = cls()
        theses = session.exec(select(Thesis).order_by(Thesis.id)).all()
        links = session.exec(select(ThesisSupervisor)).all()
        supervisors: dict[int, set[int]] = defaultdict(set)
        for link in links:
            supervisors[link.thesis_id].add(link.lecturer_id)

        for thesis in theses:
            index.add(
                ThesisCandidate(
                    title=thesis.title,
                    title_hash=thesis.title_hash,
                    year=thesis.year,
                    nim_norm=normalize_nim(thesis.nim),
                    supervisor_ids=frozenset(supervisors.get(thesis.id, set())),
                    thesis_id=thesis.id,
                )
            )
        return index

    def add(self, candidate: ThesisCandidate) -> None:
        if not candidate.title_hash:
            return
        self.by_hash[candidate.title_hash].append(candidate)
        if candidate.nim_norm:
            self.by_nim[candidate.nim_norm].append(candidate)
        if candidate.year is not None:
            for lecturer_id in candidate.supervisor_ids:
                self.by_supervisor_year[(lecturer_id, candidate.year)].append(candidate)

    def exact_matches(self, incoming: ThesisCandidate) -> list[tuple[ThesisCandidate, str]]:
        found: dict[tuple[int | None, int | None], tuple[ThesisCandidate, str]] = {}
        if incoming.nim_norm:
            for candidate in self.by_nim.get(incoming.nim_norm, []):
                found[(candidate.thesis_id, candidate.row_number)] = (candidate, "nim")
        for candidate in self.by_hash.get(incoming.title_hash, []):
            if candidate.year == incoming.year:
                key = (candidate.thesis_id, candidate.row_number)
                found.setdefault(key, (candidate, "judul_tahun"))
        return list(found.values())

    def hash_candidates(self, incoming: ThesisCandidate) -> list[ThesisCandidate]:
        return self.by_hash.get(incoming.title_hash, [])

    def fuzzy_candidates(self, incoming: ThesisCandidate) -> list[ThesisCandidate]:
        if incoming.year is None or not incoming.supervisor_ids:
            return []
        found: dict[tuple[int | None, int | None], ThesisCandidate] = {}
        for lecturer_id in incoming.supervisor_ids:
            for year in (incoming.year - 1, incoming.year, incoming.year + 1):
                for candidate in self.by_supervisor_year.get((lecturer_id, year), []):
                    found[(candidate.thesis_id, candidate.row_number)] = candidate
        return list(found.values())


def _candidate_sort_key(item: tuple[ThesisCandidate, str]) -> tuple[bool, int]:
    candidate, _ = item
    if candidate.thesis_id is not None:
        return False, candidate.thesis_id
    return True, candidate.row_number or 0


def normalize_nim(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if re.fullmatch(r"\d+[.,]0+", text):
        text = re.split(r"[.,]", text, maxsplit=1)[0]
    if re.fullmatch(r"\d+(?:[.,]\d+)?[eE][+-]?\d+", text):
        try:
            return str(int(float(text.replace(",", "."))))
        except ValueError:
            pass
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


def normalize_header(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def detect_mapping(headers: list[str]) -> dict[str, int | None]:
    normalized = [normalize_header(header) for header in headers]
    used: set[int] = set()
    mapping: dict[str, int | None] = {}
    for field_info in MAPPING_FIELDS:
        found: int | None = None
        for synonym in field_info.synonyms:
            for index, header in enumerate(normalized):
                if index in used or not header:
                    continue
                if header == synonym or header.startswith(f"{synonym} "):
                    found = index
                    break
            if found is not None:
                break
        mapping[field_info.key] = found
        if found is not None:
            used.add(found)
    return mapping


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Berkas harus berupa teks UTF-8 atau Windows-1252.")


def _pick_delimiter(text: str) -> str:
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return ","
    candidates = [delimiter for delimiter in ",;\t|" if delimiter in first_line]
    if not candidates:
        return ","
    scored = []
    for delimiter in candidates:
        try:
            columns = len(next(csv.reader([first_line], delimiter=delimiter)))
        except csv.Error:
            columns = 0
        scored.append((columns, first_line.count(delimiter), delimiter))
    return max(scored)[2]


def _trim_values(values: Iterable[Any], width: int) -> list[str]:
    cells = [_cell_text(value) for value in values]
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) > width:
        cells = cells[:width]
    cells.extend([""] * (width - len(cells)))
    return cells


def _parse_csv(content: bytes) -> ParsedFile:
    text = _decode_text(content)
    delimiter = _pick_delimiter(text)
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        raw_rows = list(reader)
    except csv.Error as error:
        raise ValueError(f"CSV tidak bisa dibaca: {error}") from error
    return _build_parsed(raw_rows)


def _parse_xlsx(content: bytes) -> ParsedFile:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # openpyxl melempar beberapa tipe untuk berkas rusak.
        raise ValueError(f"XLSX tidak bisa dibaca: {error}") from error
    try:
        if not workbook.worksheets:
            raise ValueError("Berkas XLSX tidak punya lembar kerja.")
        worksheet = workbook.worksheets[0]
        raw_rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    return _build_parsed(raw_rows)


def _build_parsed(raw_rows: list[list[Any]]) -> ParsedFile:
    header_index = None
    for index, row in enumerate(raw_rows):
        if any(_cell_text(value) for value in row):
            header_index = index
            break
    if header_index is None:
        raise ValueError("Berkas tidak berisi baris judul kolom.")

    header_values = [_cell_text(value) for value in raw_rows[header_index]]
    while header_values and not header_values[-1]:
        header_values.pop()
    if len(header_values) < 2:
        raise ValueError("Berkas minimal punya dua kolom: judul dan pembimbing 1.")

    headers = [value or f"Kolom {index + 1}" for index, value in enumerate(header_values)]
    rows: list[ParsedRow] = []
    for offset, raw in enumerate(raw_rows[header_index + 1 :], start=header_index + 2):
        values = _trim_values(raw, len(headers))
        if any(values):
            rows.append(ParsedRow(row_number=offset, values=values))
    if not rows:
        raise ValueError("Berkas tidak berisi baris data.")
    return ParsedFile(headers=headers, rows=rows)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_upload(filename: str, content: bytes) -> ParsedFile:
    if not content:
        raise ValueError("Berkas kosong.")
    lower = (filename or "").lower()
    if lower.endswith(".csv"):
        return _parse_csv(content)
    if lower.endswith(".xlsx"):
        return _parse_xlsx(content)
    raise ValueError("Berkas harus .csv atau .xlsx.")


def create_batch(session: Session, filename: str, content: bytes) -> ImportBatch:
    parsed = parse_upload(filename, content)
    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    batch = ImportBatch(
        filename=safe_name or "tanpa-nama",
        file_hash=hashlib.sha256(content).hexdigest(),
        status="mapping",
        summary_json={
            "headers": parsed.headers,
            "mapping": detect_mapping(parsed.headers),
            "summary": {},
        },
    )
    session.add(batch)
    session.flush()
    for row in parsed.rows:
        session.add(
            ImportRow(
                batch_id=batch.id,
                row_number=row.row_number,
                raw_json={"values": row.values},
            )
        )
    session.commit()
    session.refresh(batch)
    return batch


def validate_mapping(headers: list[str], mapping: dict[str, Any]) -> dict[str, int | None]:
    cleaned: dict[str, int | None] = {}
    used: dict[int, str] = {}
    for field_info in MAPPING_FIELDS:
        raw = mapping.get(field_info.key)
        index: int | None
        if raw is None or str(raw).strip() == "":
            index = None
        else:
            try:
                index = int(raw)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Kolom untuk {field_info.label} tidak valid.") from error
            if index < 0 or index >= len(headers):
                raise ValueError(f"Kolom untuk {field_info.label} tidak ada di berkas.")
            if index in used:
                raise ValueError(
                    f"Kolom {headers[index]} dipakai untuk {used[index]} dan {field_info.label}."
                )
            used[index] = field_info.label
        if field_info.required and index is None:
            raise ValueError(f"Kolom {field_info.label.lower()} wajib dipetakan.")
        cleaned[field_info.key] = index
    return cleaned


def _cell(values: list[str], index: int | None) -> str:
    if index is None or index >= len(values):
        return ""
    return values[index].strip()


def _year_from_text(value: str) -> int | None:
    match = YEAR_RE.search(value or "")
    return int(match.group(0)) if match else None


def _normalized_row(values: list[str], mapping: dict[str, int | None]) -> dict[str, Any]:
    title = _cell(values, mapping.get("judul"))
    supervisor_raw = []
    p1 = _cell(values, mapping.get("pembimbing1"))
    p2 = _cell(values, mapping.get("pembimbing2"))
    if p1:
        supervisor_raw.append({"role": 1, "name": p1})
    if p2 and normalize_person_name(p2) != normalize_person_name(p1):
        supervisor_raw.append({"role": 2, "name": p2})

    year_text = _cell(values, mapping.get("tahun"))
    return {
        "title": title,
        "title_hash": compute_title_hash(title) if normalize_title(title) else "",
        "student_name": _cell(values, mapping.get("nama")),
        "nim": _cell(values, mapping.get("nim")),
        "nim_norm": normalize_nim(_cell(values, mapping.get("nim"))),
        "year": _year_from_text(year_text),
        "topic": _cell(values, mapping.get("topik")),
        "supervisor_raw": supervisor_raw,
        "supervisors": [],
        "unknown_supervisors": [],
        "duplicate": None,
    }


def apply_mapping(session: Session, batch: ImportBatch, mapping: dict[str, Any]) -> dict[str, Any]:
    if batch.status != "mapping":
        raise ValueError("Pemetaan kolom hanya bisa diubah saat status pemetaan.")
    payload = batch.summary_json or {}
    headers = list(payload.get("headers") or [])
    cleaned = validate_mapping(headers, mapping)
    rows = session.exec(
        select(ImportRow)
        .where(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number, ImportRow.id)
    ).all()
    for row in rows:
        values = list((row.raw_json or {}).get("values") or [])
        row.normalized_json = _normalized_row(values, cleaned)
        session.add(row)
    session.flush()
    _evaluate_rows(session, batch, rows, preserve_manual=False)
    payload = dict(batch.summary_json or {})
    payload["mapping"] = cleaned
    batch.summary_json = payload
    batch.status = "preview"
    session.commit()
    return summary_of(batch)


def _candidate_from_data(data: dict[str, Any]) -> ThesisCandidate | None:
    if not data.get("title_hash"):
        return None
    supervisor_ids = {
        int(item["lecturer_id"])
        for item in data.get("supervisors", [])
        if item.get("lecturer_id") is not None
    }
    return ThesisCandidate(
        title=str(data.get("title") or ""),
        title_hash=str(data.get("title_hash") or ""),
        year=data.get("year"),
        nim_norm=str(data.get("nim_norm") or ""),
        supervisor_ids=frozenset(supervisor_ids),
        row_number=data.get("row_number"),
    )


def _resolve_supervisors(data: dict[str, Any], lookup: dict[str, Lecturer]) -> list[str]:
    resolved: list[dict[str, Any]] = []
    unknown: list[str] = []
    seen_lecturers: set[int] = set()
    seen_unknown: set[str] = set()
    for item in data.get("supervisor_raw", []):
        raw = str(item.get("name") or "").strip()
        normalized = normalize_person_name(raw)
        if not normalized:
            continue
        lecturer = lookup.get(normalized)
        if lecturer is None or lecturer.id is None:
            if normalized not in seen_unknown:
                unknown.append(raw)
                seen_unknown.add(normalized)
            continue
        if lecturer.id in seen_lecturers:
            continue
        seen_lecturers.add(lecturer.id)
        resolved.append(
            {
                "role": int(item.get("role") or 1),
                "lecturer_id": lecturer.id,
                "name": lecturer.name,
                "raw": raw,
            }
        )
    data["supervisors"] = resolved
    data["unknown_supervisors"] = unknown
    return unknown


def _candidate_label(candidate: ThesisCandidate) -> str:
    if candidate.thesis_id is not None:
        return f"skripsi #{candidate.thesis_id}"
    return f"baris #{candidate.row_number} berkas ini"


def _percent(value: float) -> str:
    return f"{value * 100:.1f}".replace(".", ",")


def _duplicate_decision(
    candidate: ThesisCandidate, index: CandidateIndex
) -> tuple[str, str, dict[str, Any] | None]:
    exact = sorted(index.exact_matches(candidate), key=_candidate_sort_key)
    if exact:
        match, reason = exact[0]
        label = _candidate_label(match)
        if reason == "nim":
            note = f"NIM sama dengan {label}; baris dilewati."
        else:
            note = f"Judul dan tahun sama dengan {label}; baris dilewati."
        return (
            "exact",
            note,
            {
                "kind": "exact",
                "reason": reason,
                "match": label,
            },
        )

    review_match: ThesisCandidate | None = None
    similar_match: ThesisCandidate | None = None
    for match in index.hash_candidates(candidate):
        if match.year == candidate.year:
            continue
        if candidate.year is None or match.year is None or abs(candidate.year - match.year) > 1:
            review_match = match
            break
        if candidate.supervisor_ids & match.supervisor_ids:
            similar_match = similar_match or match
        else:
            review_match = match
            break

    if review_match is not None:
        label = _candidate_label(review_match)
        return (
            "review",
            (f"{label} punya judul sama tetapi tahunnya berbeda; perlu review."),
            {
                "kind": "review",
                "reason": "judul_tahun",
                "match": label,
            },
        )

    if similar_match is not None:
        label = _candidate_label(similar_match)
        return (
            "similar",
            (f"Judul sama dengan {label} dan pembimbing beririsan; baris dilewati."),
            {
                "kind": "similar",
                "reason": "judul_pembimbing",
                "match": label,
                "similarity": 1.0,
            },
        )

    best_similar: tuple[float, ThesisCandidate] | None = None
    best_review: tuple[float, ThesisCandidate] | None = None
    for match in index.fuzzy_candidates(candidate):
        score = similarity(candidate.title, match.title)
        if score > 0.90 and (best_similar is None or score > best_similar[0]):
            best_similar = (score, match)
        elif 0.80 <= score <= 0.90 and (best_review is None or score > best_review[0]):
            best_review = (score, match)

    if best_similar is not None:
        score, match = best_similar
        label = _candidate_label(match)
        return (
            "similar",
            (
                f"Judul mirip {_percent(score)}% dengan {label} "
                "(pembimbing dan tahun berdekatan); baris dilewati."
            ),
            {
                "kind": "similar",
                "reason": "kemiripan",
                "match": label,
                "similarity": round(score, 4),
            },
        )

    if best_review is not None:
        score, match = best_review
        label = _candidate_label(match)
        return (
            "review",
            (
                f"Judul mirip {_percent(score)}% dengan {label} "
                "(pembimbing dan tahun berdekatan); perlu review."
            ),
            {
                "kind": "review",
                "reason": "kemiripan",
                "match": label,
                "similarity": round(score, 4),
            },
        )

    return "new", "", None


def _evaluate_rows(
    session: Session,
    batch: ImportBatch,
    rows: list[ImportRow],
    *,
    preserve_manual: bool,
) -> None:
    lookup = lecturer_lookup(session)
    index = CandidateIndex.from_session(session)
    for row in rows:
        data = dict(row.normalized_json or {})
        data["row_number"] = row.row_number
        previous = row.decision
        unknown = _resolve_supervisors(data, lookup)
        title = str(data.get("title") or "")
        valid_title = bool(data.get("title_hash")) and bool(normalize_title(title))
        supervisor_raw = data.get("supervisor_raw") or []
        first_supervisor = next(
            (item for item in supervisor_raw if int(item.get("role") or 1) == 1), None
        )
        first_supervisor_raw = str((first_supervisor or {}).get("name") or "").strip()

        if not valid_title:
            decision, note, duplicate = "invalid", "Judul kosong.", None
        elif not first_supervisor_raw:
            decision, note, duplicate = "invalid", "Pembimbing 1 kosong.", None
        elif not normalize_person_name(first_supervisor_raw):
            decision, note, duplicate = "invalid", "Pembimbing 1 tidak valid.", None
        else:
            candidate = _candidate_from_data(data)
            if candidate is None:
                decision, note, duplicate = "invalid", "Judul kosong.", None
            else:
                decision, note, duplicate = _duplicate_decision(candidate, index)
                if decision in ("new", "review") and unknown:
                    unknown_note = "Pembimbing tidak dikenal: " + ", ".join(unknown) + "."
                    note = f"{unknown_note} {note}".strip() if note else unknown_note
                    decision = "unknown_supervisor"
                if candidate is not None:
                    index.add(candidate)

        if preserve_manual:
            if previous == "skip" and decision not in ("invalid", "exact", "similar"):
                decision = "skip"
                note = f"Dilewati manual. {note}".strip()
            elif previous == "keep" and decision == "review":
                decision = "keep"
                note = f"Ditambahkan manual. {note}".strip()

        row.decision = decision
        row.note = note
        data["duplicate"] = duplicate
        row.normalized_json = data
        session.add(row)

    batch.summary_json = _with_summary(batch.summary_json, _summarize(rows))
    session.add(batch)


def _summarize(rows: list[ImportRow]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    unknown_names: set[str] = set()
    for row in rows:
        counts[row.decision or ""] += 1
        if row.decision != "unknown_supervisor":
            continue
        data = row.normalized_json or {}
        for name in data.get("unknown_supervisors", []):
            if name:
                unknown_names.add(str(name))

    new = counts["new"] + counts["keep"]
    duplicate = counts["exact"] + counts["similar"] + counts["skip"]
    inserted = sum(1 for row in rows if row.thesis_id is not None)
    return {
        "total": len(rows),
        "new": new,
        "duplicate": duplicate,
        "review": counts["review"],
        "unknown": counts["unknown_supervisor"],
        "invalid": counts["invalid"],
        "exact": counts["exact"],
        "similar": counts["similar"],
        "skip": counts["skip"],
        "keep": counts["keep"],
        "inserted": inserted,
        "unknown_names": sorted(unknown_names),
    }


def _with_summary(payload: dict[str, Any] | None, summary: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload or {})
    updated["summary"] = summary
    return updated


def summary_of(batch: ImportBatch) -> dict[str, Any]:
    payload = batch.summary_json or {}
    summary = payload.get("summary") or {}
    defaults = {
        "total": 0,
        "new": 0,
        "duplicate": 0,
        "review": 0,
        "unknown": 0,
        "invalid": 0,
        "exact": 0,
        "similar": 0,
        "skip": 0,
        "keep": 0,
        "inserted": 0,
        "unknown_names": [],
    }
    defaults.update(summary)
    return defaults


def mapping_of(batch: ImportBatch) -> dict[str, int | None]:
    payload = batch.summary_json or {}
    mapping = payload.get("mapping") or {}
    result: dict[str, int | None] = {}
    for field_info in MAPPING_FIELDS:
        value = mapping.get(field_info.key)
        result[field_info.key] = int(value) if value is not None else None
    return result


def headers_of(batch: ImportBatch) -> list[str]:
    return list((batch.summary_json or {}).get("headers") or [])


def add_alias(session: Session, batch: ImportBatch, raw_name: str, lecturer_id: int) -> None:
    if batch.status != "preview":
        raise ValueError("Alias hanya bisa dipetakan pada batch pratinjau.")
    normalized = normalize_person_name(raw_name)
    if not normalized:
        raise ValueError("Nama pembimbing tidak valid.")
    rows = session.exec(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
    known_unknown = {
        normalize_person_name(name)
        for row in rows
        for name in (row.normalized_json or {}).get("unknown_supervisors", [])
        if name
    }
    if normalized not in known_unknown:
        raise ValueError("Nama itu tidak ada di daftar pembimbing tak dikenal.")

    lecturer = session.get(Lecturer, lecturer_id)
    if lecturer is None:
        raise ValueError("Dosen tidak ditemukan.")
    existing = session.exec(
        select(LecturerAlias).where(LecturerAlias.alias_normalized == normalized)
    ).first()
    if existing is not None:
        if existing.lecturer_id != lecturer_id:
            raise ValueError("Nama itu sudah menjadi alias dosen lain.")
        _evaluate_rows(session, batch, rows, preserve_manual=True)
        session.commit()
        return

    for other in session.exec(select(Lecturer)).all():
        if other.id != lecturer_id and normalize_person_name(other.name) == normalized:
            raise ValueError("Nama itu sudah dipakai dosen lain.")

    session.add(
        LecturerAlias(
            lecturer_id=lecturer_id,
            alias_normalized=normalized,
            created_by_batch_id=batch.id,
        )
    )
    session.flush()
    _evaluate_rows(session, batch, rows, preserve_manual=True)
    session.commit()


def set_row_decision(session: Session, batch: ImportBatch, row: ImportRow, decision: str) -> None:
    if batch.status != "preview":
        raise ValueError("Keputusan hanya bisa diubah pada batch pratinjau.")
    if decision not in ("keep", "skip"):
        raise ValueError("Keputusan tidak dikenal.")
    if row.decision != "review":
        raise ValueError("Baris ini tidak sedang menunggu keputusan.")
    row.decision = decision
    prefix = "Ditambahkan manual." if decision == "keep" else "Dilewati manual."
    row.note = f"{prefix} {row.note}".strip()
    session.add(row)
    _refresh_batch_summary(session, batch)
    session.commit()


def set_all_review_decisions(session: Session, batch: ImportBatch, decision: str) -> int:
    if batch.status != "preview":
        raise ValueError("Keputusan hanya bisa diubah pada batch pratinjau.")
    if decision not in ("keep", "skip"):
        raise ValueError("Keputusan tidak dikenal.")
    rows = session.exec(
        select(ImportRow).where(ImportRow.batch_id == batch.id, ImportRow.decision == "review")
    ).all()
    prefix = "Ditambahkan manual." if decision == "keep" else "Dilewati manual."
    for row in rows:
        row.decision = decision
        row.note = f"{prefix} {row.note}".strip()
        session.add(row)
    _refresh_batch_summary(session, batch)
    session.commit()
    return len(rows)


def _refresh_batch_summary(session: Session, batch: ImportBatch) -> None:
    rows = session.exec(
        select(ImportRow)
        .where(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number, ImportRow.id)
    ).all()
    batch.summary_json = _with_summary(batch.summary_json, _summarize(rows))
    session.add(batch)


def confirm_batch(session: Session, batch: ImportBatch) -> dict[str, Any]:
    if batch.status != "preview":
        raise ValueError("Hanya batch pratinjau yang bisa dikonfirmasi.")
    rows = session.exec(
        select(ImportRow)
        .where(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_number, ImportRow.id)
    ).all()
    review_count = sum(1 for row in rows if row.decision == "review")
    if review_count:
        raise ValueError(
            f"Masih ada {review_count} baris yang perlu diputuskan "
            "(tambahkan atau lewati) sebelum konfirmasi."
        )
    unknown_count = sum(1 for row in rows if row.decision == "unknown_supervisor")
    if unknown_count:
        raise ValueError(
            f"Masih ada {unknown_count} baris dengan pembimbing tak dikenal. Petakan dulu ke dosen."
        )

    version = get_taxonomy_version(session)
    thesis_ids: list[int] = []
    try:
        for row in rows:
            if row.decision not in ("new", "keep"):
                continue
            data = row.normalized_json or {}
            thesis = Thesis(
                title=str(data.get("title") or "").strip(),
                title_hash=str(data.get("title_hash") or ""),
                student_name=str(data.get("student_name") or "").strip(),
                nim=str(data.get("nim") or "").strip(),
                year=data.get("year"),
                import_batch_id=batch.id,
            )
            session.add(thesis)
            session.flush()
            for item in data.get("supervisors", []):
                session.add(
                    ThesisSupervisor(
                        thesis_id=thesis.id,
                        lecturer_id=int(item["lecturer_id"]),
                        role=int(item.get("role") or 1),
                    )
                )
            for topic in _imported_topics(session, str(data.get("topic") or "")):
                session.add(
                    ThesisTopic(
                        thesis_id=thesis.id,
                        topic_id=topic.id,
                        confidence=1.0,
                        source="import",
                        locked=True,
                        taxonomy_version=version,
                    )
                )
            row.thesis_id = thesis.id
            session.add(row)
            thesis_ids.append(thesis.id)

        if thesis_ids:
            reclassify_theses(session, thesis_ids=thesis_ids, commit=False)

        batch.status = "committed"
        batch.confirmed_at = utcnow()
        batch.summary_json = _with_summary(batch.summary_json, _summarize(rows))
        session.add(batch)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return summary_of(batch)


def _imported_topics(session: Session, raw: str) -> list[Topic]:
    if not raw.strip():
        return []
    active = session.exec(select(Topic).where(Topic.active.is_(True))).all()
    by_norm = {normalize_keyword(topic.name): topic for topic in active}
    by_id = {topic.id: topic for topic in active}
    matched: dict[int, Topic] = {}
    for part in TOPIC_SPLIT_RE.split(raw):
        topic = by_norm.get(normalize_keyword(part))
        if topic is None:
            continue
        root = by_id.get(topic.parent_id) if topic.parent_id else topic
        if root is None or root.id is None:
            continue
        matched[root.id] = root
    return sorted(matched.values(), key=lambda item: item.name)


def rollback_batch(session: Session, batch: ImportBatch) -> int:
    if batch.status != "committed":
        raise ValueError("Hanya batch yang sudah dikonfirmasi yang bisa dibatalkan.")
    rows = session.exec(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
    thesis_ids = [
        thesis.id
        for thesis in session.exec(select(Thesis).where(Thesis.import_batch_id == batch.id)).all()
        if thesis.id is not None
    ]

    for row in rows:
        row.thesis_id = None
        session.add(row)
    session.flush()

    if thesis_ids:
        for link in session.exec(
            select(ThesisSupervisor).where(ThesisSupervisor.thesis_id.in_(thesis_ids))
        ).all():
            session.delete(link)
        for label in session.exec(
            select(ThesisTopic).where(ThesisTopic.thesis_id.in_(thesis_ids))
        ).all():
            session.delete(label)
        session.flush()
        for thesis in session.exec(select(Thesis).where(Thesis.id.in_(thesis_ids))).all():
            session.delete(thesis)
        session.flush()

    for alias in session.exec(
        select(LecturerAlias).where(LecturerAlias.created_by_batch_id == batch.id)
    ).all():
        session.delete(alias)

    batch.status = "rolled_back"
    batch.summary_json = _with_summary(batch.summary_json, _summarize(rows))
    payload = dict(batch.summary_json or {})
    payload["rollback"] = {
        "at": utcnow().isoformat(),
        "theses": len(thesis_ids),
    }
    batch.summary_json = payload
    session.add(batch)
    session.commit()
    return len(thesis_ids)


def cleanup_expired_batches(session: Session, now: datetime | None = None) -> int:
    current = now or utcnow()
    cutoff = _aware(current) - PREVIEW_TTL
    batches = session.exec(
        select(ImportBatch).where(ImportBatch.status.in_(("mapping", "preview")))
    ).all()
    expired = [
        batch
        for batch in batches
        if batch.created_at is not None and _aware(batch.created_at) <= cutoff
    ]
    for batch in expired:
        for alias in session.exec(
            select(LecturerAlias).where(LecturerAlias.created_by_batch_id == batch.id)
        ).all():
            session.delete(alias)
        for row in session.exec(select(ImportRow).where(ImportRow.batch_id == batch.id)).all():
            session.delete(row)
        session.delete(batch)
    if expired:
        session.commit()
    return len(expired)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
