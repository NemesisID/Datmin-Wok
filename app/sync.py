"""Orkestrasi sinkronisasi publikasi lewat tabel sync_jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, select

from app.classify import reclassify_papers
from app.config import Settings
from app.dedupe import find_match, merge_raw_into, paper_from_raw
from app.models import (
    Lecturer,
    LecturerOpenAlexId,
    LecturerPaper,
    PaperDuplicate,
    SyncJob,
    utcnow,
)
from app.providers.base import ProviderResult, PublicationProvider, RawPaper

SYNC_SKIP_DAYS = 7
STALE_MINUTES = 30
MAX_ERROR_LENGTH = 500


@dataclass
class StoreStats:
    new: int = 0
    merged: int = 0
    duplicates: int = 0
    touched: list[int] = field(default_factory=list)


@dataclass
class SyncSummary:
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    new_papers: int = 0
    merged: int = 0
    duplicates: int = 0
    credits: float = 0.0


def publication_window_start(settings: Settings, today: date | None = None) -> date:
    today = today or date.today()
    try:
        return today.replace(year=today.year - settings.publication_window_years)
    except ValueError:  # 29 Februari
        return today.replace(year=today.year - settings.publication_window_years, day=28)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def enqueue_job(session: Session, lecturer_id: int, source: str = "openalex") -> SyncJob:
    existing = session.exec(
        select(SyncJob).where(
            SyncJob.lecturer_id == lecturer_id,
            SyncJob.source == source,
            SyncJob.status == "pending",
        )
    ).first()
    if existing:
        return existing
    job = SyncJob(lecturer_id=lecturer_id, source=source, status="pending")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def fail_stale_jobs(session: Session, now: datetime | None = None) -> int:
    """Tandai job running yang menggantung lebih dari 30 menit sebagai gagal."""
    now = now or utcnow()
    stale = 0
    for job in session.exec(select(SyncJob).where(SyncJob.status == "running")).all():
        started = _aware(job.started_at)
        if started is None or started < now - timedelta(minutes=STALE_MINUTES):
            job.status = "failed"
            job.finished_at = now
            job.error = "Proses berhenti lebih dari 30 menit. Job bisa diulang."
            session.add(job)
            stale += 1
    if stale:
        session.commit()
    return stale


def recently_synced(lecturer: Lecturer, now: datetime, days: int = SYNC_SKIP_DAYS) -> bool:
    last = _aware(lecturer.last_synced_at)
    return last is not None and last > now - timedelta(days=days)


def _ensure_link(session: Session, lecturer_id: int, paper_id: int) -> None:
    existing = session.exec(
        select(LecturerPaper).where(
            LecturerPaper.lecturer_id == lecturer_id,
            LecturerPaper.paper_id == paper_id,
        )
    ).first()
    if existing is None:
        session.add(LecturerPaper(lecturer_id=lecturer_id, paper_id=paper_id))


def store_papers(
    session: Session, lecturer: Lecturer, papers: list[RawPaper], source: str
) -> StoreStats:
    """Simpan hasil satu sumber. Paper yang sudah ada digabung, bukan diduplikasi."""
    stats = StoreStats()
    for raw in papers:
        if not raw.title.strip():
            continue
        match = find_match(session, raw)
        needs_classify = True
        if match.paper is not None:
            paper = match.paper
            if merge_raw_into(paper, raw, source):
                stats.merged += 1
            else:
                needs_classify = False
            session.add(paper)
        else:
            paper = paper_from_raw(raw, source)
            session.add(paper)
            session.flush()
            stats.new += 1
            if match.candidate is not None:
                session.add(
                    PaperDuplicate(
                        paper_id=paper.id,
                        candidate_id=match.candidate.id,
                        similarity=round(match.similarity, 4),
                    )
                )
                stats.duplicates += 1
        _ensure_link(session, lecturer.id, paper.id)
        if needs_classify and paper.id not in stats.touched:
            stats.touched.append(paper.id)
    session.commit()
    return stats


def run_job(
    session: Session,
    job: SyncJob,
    provider: PublicationProvider,
    lecturer: Lecturer,
    author_ids: list[str],
    since: date,
    now: datetime | None = None,
) -> tuple[ProviderResult, StoreStats]:
    job.status = "running"
    job.attempts += 1
    job.started_at = now or utcnow()
    job.error = ""
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        result = provider.fetch(lecturer, author_ids, since)
        stats = store_papers(session, lecturer, result.papers, provider.name)
        reclassify_papers(session, paper_ids=stats.touched)
    except Exception as error:
        session.rollback()
        failed = session.get(SyncJob, job.id)
        if failed is not None:
            failed.status = "failed"
            failed.finished_at = utcnow()
            failed.error = str(error)[:MAX_ERROR_LENGTH]
            session.add(failed)
            session.commit()
        raise

    finished = session.get(SyncJob, job.id)
    if finished is not None:
        finished.status = "done"
        finished.finished_at = utcnow()
        finished.new_papers = stats.new
        finished.credits_used = float(result.credits)
        session.add(finished)
    lecturer.last_synced_at = utcnow()
    lecturer.updated_at = utcnow()
    session.add(lecturer)
    session.commit()
    return result, stats


def run_jobs(
    session: Session,
    provider: PublicationProvider,
    since: date,
    *,
    force: bool = False,
    lecturer_id: int | None = None,
    now: datetime | None = None,
) -> SyncSummary:
    """Jalankan job sinkronisasi untuk dosen aktif yang punya ID OpenAlex."""
    now = now or utcnow()
    summary = SyncSummary()
    fail_stale_jobs(session, now)

    if lecturer_id is not None:
        lecturer = session.get(Lecturer, lecturer_id)
        if lecturer is None:
            raise ValueError(f"Dosen {lecturer_id} tidak ditemukan.")
        lecturers = [lecturer]
    else:
        lecturers = list(session.exec(select(Lecturer).where(Lecturer.active.is_(True))).all())

    for lecturer in lecturers:
        author_ids = [
            row.openalex_author_id
            for row in session.exec(
                select(LecturerOpenAlexId).where(LecturerOpenAlexId.lecturer_id == lecturer.id)
            ).all()
        ]
        if not author_ids:
            summary.skipped += 1
            continue

        pending = session.exec(
            select(SyncJob).where(
                SyncJob.lecturer_id == lecturer.id,
                SyncJob.source == provider.name,
                SyncJob.status == "pending",
            )
        ).first()
        # Job yang dibuat lewat tombol admin adalah permintaan eksplisit,
        # jadi jangan dilewati hanya karena baru disinkronkan.
        if pending is None and not force and recently_synced(lecturer, now):
            summary.skipped += 1
            continue

        job = pending or enqueue_job(session, lecturer.id, source=provider.name)
        try:
            result, stats = run_job(session, job, provider, lecturer, author_ids, since, now)
        except Exception:
            summary.failed += 1
            continue

        summary.synced += 1
        summary.credits += result.credits
        summary.new_papers += stats.new
        summary.merged += stats.merged
        summary.duplicates += stats.duplicates

    return summary
