"""Normalisasi nama dosen untuk pencocokan pembimbing pada impor skripsi."""

from __future__ import annotations

import re
import unicodedata

from sqlmodel import Session, select

from app.models import Lecturer, LecturerAlias

NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")

TITLE_TOKENS = frozenset(
    {
        "prof",
        "profesor",
        "dr",
        "drg",
        "drh",
        "drs",
        "dra",
        "ir",
        "hj",
        "h",
        "haji",
        "hajjah",
        "ny",
        "nyi",
    }
)

# Gelar sering ditulis tanpa titik, sehingga "S.Kom." menjadi dua token: "s kom".
# Token gelar hanya dibuang dari ujung nama agar kata di tengah nama tetap utuh.
DEGREE_TOKENS = frozenset(
    {
        "a",
        "adm",
        "ag",
        "agr",
        "ak",
        "amd",
        "ant",
        "ark",
        "ars",
        "b",
        "bahasa",
        "bio",
        "budaya",
        "d",
        "des",
        "ds",
        "eko",
        "e",
        "farm",
        "filsafat",
        "fis",
        "gz",
        "h",
        "hot",
        "hukum",
        "hum",
        "hut",
        "i",
        "ind",
        "industri",
        "inf",
        "informatika",
        "informasi",
        "inggris",
        "kar",
        "ked",
        "kedokteran",
        "kehutanan",
        "kel",
        "kelautan",
        "kep",
        "keperawatan",
        "kebidanan",
        "kes",
        "kesos",
        "kesehatan",
        "kim",
        "kom",
        "komunikasi",
        "komputer",
        "m",
        "man",
        "manajemen",
        "matematika",
        "md",
        "mil",
        "mus",
        "ni",
        "niaga",
        "ol",
        "p",
        "par",
        "pariwisata",
        "pd",
        "pend",
        "pendidikan",
        "perhotelan",
        "perikanan",
        "pert",
        "pertanian",
        "peternakan",
        "ph",
        "pi",
        "pol",
        "politik",
        "prof",
        "ps",
        "psi",
        "psikologi",
        "pt",
        "s",
        "sastra",
        "sc",
        "sej",
        "sen",
        "seni",
        "si",
        "sistem",
        "sis",
        "sn",
        "sos",
        "sosial",
        "stat",
        "statistika",
        "t",
        "tek",
        "teknik",
        "teknologi",
        "th",
        "tr",
        "vokasi",
    }
)

COMPACT_DEGREES = frozenset(
    {
        "sagr",
        "sak",
        "sab",
        "sadm",
        "se",
        "sfarm",
        "sh",
        "sikom",
        "sip",
        "sked",
        "skom",
        "sni",
        "spar",
        "spd",
        "spsi",
        "spt",
        "ss",
        "ssi",
        "ssos",
        "st",
        "magr",
        "mak",
        "mab",
        "madm",
        "me",
        "mfarm",
        "mh",
        "mikom",
        "mip",
        "mked",
        "mkom",
        "mni",
        "mpar",
        "mpd",
        "mpsi",
        "mpt",
        "ms",
        "msi",
        "msos",
        "mt",
    }
)


def normalize_person_name(value: str) -> str:
    """Buang gelar dan tanda baca, lalu kembalikan nama dalam huruf kecil."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = NON_WORD_RE.sub(" ", text)
    tokens = SPACE_RE.sub(" ", text).strip().split()
    if not tokens:
        return ""

    while tokens and tokens[0] in TITLE_TOKENS:
        tokens.pop(0)

    while tokens and (tokens[-1] in DEGREE_TOKENS or tokens[-1] in COMPACT_DEGREES):
        tokens.pop()

    return " ".join(tokens)


def lecturer_lookup(session: Session) -> dict[str, Lecturer]:
    """Peta nama ternormalisasi dan alias ke dosen."""
    lookup: dict[str, Lecturer] = {}
    for lecturer in session.exec(select(Lecturer).order_by(Lecturer.id)).all():
        normalized = normalize_person_name(lecturer.name)
        if normalized and normalized not in lookup:
            lookup[normalized] = lecturer
    for alias in session.exec(select(LecturerAlias).order_by(LecturerAlias.id)).all():
        lecturer = session.get(Lecturer, alias.lecturer_id)
        if lecturer is None or not alias.alias_normalized:
            continue
        lookup[alias.alias_normalized] = lecturer
    return lookup
