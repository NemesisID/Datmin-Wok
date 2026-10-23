"""Skema database. Satu sumber kebenaran untuk SQLModel dan Alembic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

LABS = ("SOLUSI", "MSI")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Meta(SQLModel, table=True):
    __tablename__ = "meta"

    key: str = Field(primary_key=True)
    value: str = ""


class Lecturer(SQLModel, table=True):
    __tablename__ = "lecturers"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    title: str = ""
    scholar_id: str | None = Field(default=None, unique=True, index=True)
    active: bool = True
    notes: str = ""
    last_synced_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class LecturerOpenAlexId(SQLModel, table=True):
    __tablename__ = "lecturer_openalex_ids"
    __table_args__ = (UniqueConstraint("lecturer_id", "openalex_author_id"),)

    id: int | None = Field(default=None, primary_key=True)
    lecturer_id: int = Field(foreign_key="lecturers.id", index=True)
    openalex_author_id: str = Field(index=True)
    display_name: str = ""
    works_count: int | None = None
    confirmed_at: datetime = Field(default_factory=utcnow)


class LecturerAlias(SQLModel, table=True):
    __tablename__ = "lecturer_aliases"
    __table_args__ = (UniqueConstraint("lecturer_id", "alias_normalized"),)

    id: int | None = Field(default=None, primary_key=True)
    lecturer_id: int = Field(foreign_key="lecturers.id", index=True)
    alias_normalized: str
    created_by_batch_id: int | None = Field(default=None, foreign_key="import_batches.id")


class Paper(SQLModel, table=True):
    __tablename__ = "papers"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    title_hash: str = Field(index=True)
    year: int | None = Field(default=None, index=True)
    venue: str = ""
    doi: str | None = None
    doi_norm: str | None = Field(default=None, unique=True, index=True)
    abstract: str | None = None
    citations: int = 0
    scholar_pub_id: str | None = Field(default=None, index=True)
    openalex_id: str | None = Field(default=None, unique=True)
    sources: list[str] | None = Field(default=None, sa_column=Column(JSON))
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LecturerPaper(SQLModel, table=True):
    __tablename__ = "lecturer_papers"
    __table_args__ = (UniqueConstraint("lecturer_id", "paper_id"),)

    id: int | None = Field(default=None, primary_key=True)
    lecturer_id: int = Field(foreign_key="lecturers.id", index=True)
    paper_id: int = Field(foreign_key="papers.id", index=True)


class PaperDuplicate(SQLModel, table=True):
    __tablename__ = "paper_duplicates"
    __table_args__ = (UniqueConstraint("paper_id", "candidate_id"),)

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="papers.id", index=True)
    candidate_id: int = Field(foreign_key="papers.id", index=True)
    similarity: float = 0.0
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Topic(SQLModel, table=True):
    __tablename__ = "topics"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    parent_id: int | None = Field(default=None, foreign_key="topics.id", index=True)
    active: bool = True
    sort_order: int = 0


class TopicLab(SQLModel, table=True):
    __tablename__ = "topic_labs"
    __table_args__ = (UniqueConstraint("topic_id", "lab"),)

    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    lab: str


class TopicKeyword(SQLModel, table=True):
    __tablename__ = "topic_keywords"
    __table_args__ = (UniqueConstraint("topic_id", "keyword_norm"),)

    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    keyword: str
    keyword_norm: str = Field(index=True)
    weight: float = 1.0
    lang: str = ""


class PaperTopic(SQLModel, table=True):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "topic_id"),)

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="papers.id", index=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    subtopic_id: int | None = Field(default=None, foreign_key="topics.id")
    confidence: float = 0.0
    source: str = "rule"
    locked: bool = False
    taxonomy_version: int = 0


class Thesis(SQLModel, table=True):
    __tablename__ = "theses"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    title_hash: str = Field(index=True)
    student_name: str = ""
    nim: str = ""
    year: int | None = Field(default=None, index=True)
    import_batch_id: int | None = Field(default=None, foreign_key="import_batches.id")
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ThesisSupervisor(SQLModel, table=True):
    __tablename__ = "thesis_supervisors"
    __table_args__ = (UniqueConstraint("thesis_id", "lecturer_id", "role"),)

    id: int | None = Field(default=None, primary_key=True)
    thesis_id: int = Field(foreign_key="theses.id", index=True)
    lecturer_id: int = Field(foreign_key="lecturers.id", index=True)
    role: int = 1


class ThesisTopic(SQLModel, table=True):
    __tablename__ = "thesis_topics"
    __table_args__ = (UniqueConstraint("thesis_id", "topic_id"),)

    id: int | None = Field(default=None, primary_key=True)
    thesis_id: int = Field(foreign_key="theses.id", index=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)
    confidence: float = 0.0
    source: str = "rule"
    locked: bool = False
    taxonomy_version: int = 0


class ImportBatch(SQLModel, table=True):
    __tablename__ = "import_batches"

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    file_hash: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    confirmed_at: datetime | None = None
    summary_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    status: str = "preview"


class ImportRow(SQLModel, table=True):
    __tablename__ = "import_rows"

    id: int | None = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="import_batches.id", index=True)
    row_number: int
    raw_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    normalized_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    decision: str = ""
    thesis_id: int | None = Field(default=None, foreign_key="theses.id")
    note: str = ""


class SyncJob(SQLModel, table=True):
    __tablename__ = "sync_jobs"

    id: int | None = Field(default=None, primary_key=True)
    lecturer_id: int | None = Field(default=None, foreign_key="lecturers.id", index=True)
    source: str = "openalex"
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    new_papers: int = 0
    credits_used: float = 0.0
    error: str = ""


class LlmCache(SQLModel, table=True):
    __tablename__ = "llm_cache"
    __table_args__ = (UniqueConstraint("content_hash", "taxonomy_version"),)

    id: int | None = Field(default=None, primary_key=True)
    content_hash: str = Field(index=True)
    taxonomy_version: int
    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
