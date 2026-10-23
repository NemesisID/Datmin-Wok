"""Tabel FTS5 untuk pencarian judul dan venue paper."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

FTS_DDL = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        title,
        venue,
        content='papers',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_ai AFTER INSERT ON papers BEGIN
        INSERT INTO papers_fts(rowid, title, venue) VALUES (new.id, new.title, new.venue);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_ad AFTER DELETE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, venue)
        VALUES ('delete', old.id, old.title, old.venue);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_au AFTER UPDATE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, venue)
        VALUES ('delete', old.id, old.title, old.venue);
        INSERT INTO papers_fts(rowid, title, venue) VALUES (new.id, new.title, new.venue);
    END
    """,
)

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def ensure_fts(engine: Engine) -> None:
    """Buat tabel FTS dan trigger; aman dipanggil berulang."""
    with engine.begin() as connection:
        for statement in FTS_DDL:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts) VALUES ('rebuild')")


def _match_query(query: str) -> str:
    tokens = TOKEN_RE.findall(query or "")
    return " ".join(f'"{token}"*' for token in tokens)


def search_paper_ids(session: Session, query: str, limit: int = 50) -> list[int]:
    match = _match_query(query)
    if not match:
        return []
    statement = text(
        "SELECT rowid FROM papers_fts WHERE papers_fts MATCH :match ORDER BY rank LIMIT :limit"
    )
    rows = session.exec(statement, params={"match": match, "limit": limit}).all()
    return [int(row[0]) for row in rows]
