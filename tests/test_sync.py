from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from factories import seed_minimal_taxonomy
from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    Lecturer,
    LecturerOpenAlexId,
    LecturerPaper,
    Paper,
    PaperDuplicate,
    PaperTopic,
    SyncJob,
    utcnow,
)
from app.providers.base import ProviderResult, RawPaper
from app.providers.manual import ManualImportProvider
from app.sync import (
    enqueue_job,
    fail_stale_jobs,
    publication_window_start,
    run_jobs,
    store_papers,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
SINCE = date(2023, 10, 23)


class FakeProvider:
    name = "openalex"

    def __init__(self, papers: list[RawPaper], fail_for: set[int] | None = None) -> None:
        self.papers = papers
        self.fail_for = fail_for or set()
        self.calls: list[int] = []

    def fetch(self, lecturer, openalex_ids: list[str], since: date) -> ProviderResult:
        self.calls.append(lecturer.id)
        if lecturer.id in self.fail_for:
            raise RuntimeError("OpenAlex sedang mati")
        return ProviderResult(
            papers=[replace(paper, sources=list(paper.sources)) for paper in self.papers],
            credits=0.05,
            requests=1,
        )


def make_lecturer(
    session: Session,
    name: str,
    author_id: str | None = "A1",
    *,
    active: bool = True,
    last_synced_at: datetime | None = None,
) -> Lecturer:
    lecturer = Lecturer(name=name, active=active, last_synced_at=last_synced_at)
    session.add(lecturer)
    session.commit()
    session.refresh(lecturer)
    if author_id is not None:
        session.add(LecturerOpenAlexId(lecturer_id=lecturer.id, openalex_author_id=author_id))
        session.commit()
    return lecturer


def test_first_sync_inserts_then_second_sync_adds_nothing(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    provider = FakeProvider(
        [
            RawPaper(title="Paper Satu", year=2024, citations=3),
            RawPaper(title="Paper Dua", year=2025),
        ]
    )

    first = run_jobs(session, provider, SINCE, now=NOW)
    assert first.synced == 1
    assert first.new_papers == 2
    assert first.failed == 0
    assert first.credits == 0.05

    second = run_jobs(session, provider, SINCE, force=True, now=NOW)
    assert second.new_papers == 0
    assert len(session.exec(select(Paper)).all()) == 2
    assert len(session.exec(select(LecturerPaper)).all()) == 2
    assert session.get(Lecturer, lecturer.id).last_synced_at is not None


def test_recent_sync_is_skipped_without_force(session: Session) -> None:
    make_lecturer(session, "Dosen Satu", last_synced_at=NOW - timedelta(days=1))
    provider = FakeProvider([RawPaper(title="Paper Satu", year=2024)])

    summary = run_jobs(session, provider, SINCE, now=NOW)
    assert summary.skipped == 1
    assert summary.synced == 0
    assert provider.calls == []


def test_force_ignores_the_seven_day_skip(session: Session) -> None:
    make_lecturer(session, "Dosen Satu", last_synced_at=NOW - timedelta(days=1))
    provider = FakeProvider([RawPaper(title="Paper Satu", year=2024)])

    summary = run_jobs(session, provider, SINCE, force=True, now=NOW)
    assert summary.synced == 1
    assert summary.new_papers == 1
    assert provider.calls


def test_pending_admin_job_runs_even_if_recently_synced(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu", last_synced_at=NOW - timedelta(days=1))
    job = enqueue_job(session, lecturer.id)
    provider = FakeProvider([RawPaper(title="Paper Satu", year=2024)])

    summary = run_jobs(session, provider, SINCE, now=NOW)
    assert summary.synced == 1
    assert summary.skipped == 0
    session.refresh(job)
    assert job.status == "done"


def test_lecturer_without_openalex_id_is_skipped(session: Session) -> None:
    make_lecturer(session, "Dosen Tanpa ID", author_id=None)
    provider = FakeProvider([RawPaper(title="Paper", year=2024)])

    summary = run_jobs(session, provider, SINCE, now=NOW)
    assert summary.skipped == 1
    assert provider.calls == []


def test_failure_is_isolated_per_lecturer(session: Session) -> None:
    broken = make_lecturer(session, "Dosen Rusak", author_id="A1")
    healthy = make_lecturer(session, "Dosen Sehat", author_id="A2")
    provider = FakeProvider([RawPaper(title="Paper Satu", year=2024)], fail_for={broken.id})

    summary = run_jobs(session, provider, SINCE, now=NOW)
    assert summary.failed == 1
    assert summary.synced == 1
    assert summary.new_papers == 1

    jobs = session.exec(select(SyncJob).order_by(SyncJob.id)).all()
    statuses = {job.lecturer_id: job.status for job in jobs}
    assert statuses[broken.id] == "failed"
    assert statuses[healthy.id] == "done"
    failed = next(job for job in jobs if job.lecturer_id == broken.id)
    assert "mati" in failed.error
    assert session.get(Lecturer, broken.id).last_synced_at is None


def test_similar_title_is_queued_not_merged(session: Session) -> None:
    make_lecturer(session, "Dosen Satu")
    session.add(
        Paper(
            title="Sistem Informasi Manajemen Proyek",
            title_hash="hash-lama",
            year=2024,
        )
    )
    session.commit()

    provider = FakeProvider(
        [RawPaper(title="Sistem Informasi Manajemen Proyek di Indonesia", year=2024)]
    )
    summary = run_jobs(session, provider, SINCE, now=NOW)
    assert summary.new_papers == 1
    assert summary.duplicates == 1
    assert len(session.exec(select(Paper)).all()) == 2

    duplicate = session.exec(select(PaperDuplicate)).one()
    assert duplicate.status == "pending"
    assert duplicate.similarity >= 0.9


def test_openalex_and_scholar_export_become_one_row(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    run_jobs(
        session,
        FakeProvider([RawPaper(title="Sistem Informasi Manajemen Proyek", year=2024)]),
        SINCE,
        now=NOW,
    )

    provider = ManualImportProvider(
        "ekspor.csv",
        b"Title,Year\nSistem Informasi Manajemen Proyek,2024\n",
    )
    result = provider.fetch(lecturer, [], SINCE)
    store_papers(session, lecturer, result.papers, provider.name)

    papers = session.exec(select(Paper)).all()
    assert len(papers) == 1
    assert papers[0].sources == ["manual", "openalex"]
    assert len(session.exec(select(LecturerPaper)).all()) == 1


def test_stale_running_job_is_marked_failed(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    job = SyncJob(
        lecturer_id=lecturer.id,
        status="running",
        started_at=NOW - timedelta(minutes=31),
    )
    session.add(job)
    session.commit()

    assert fail_stale_jobs(session, NOW) == 1
    session.refresh(job)
    assert job.status == "failed"
    assert "30 menit" in job.error


def test_fresh_running_job_is_left_alone(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    job = SyncJob(
        lecturer_id=lecturer.id,
        status="running",
        started_at=NOW - timedelta(minutes=5),
    )
    session.add(job)
    session.commit()

    assert fail_stale_jobs(session, NOW) == 0
    session.refresh(job)
    assert job.status == "running"


def test_enqueue_job_reuses_pending_job(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Satu")
    first = enqueue_job(session, lecturer.id)
    second = enqueue_job(session, lecturer.id)
    assert first.id == second.id
    assert len(session.exec(select(SyncJob)).all()) == 1


def test_explicit_lecturer_id_can_sync_inactive_lecturer(session: Session) -> None:
    lecturer = make_lecturer(session, "Dosen Nonaktif", active=False)
    provider = FakeProvider([RawPaper(title="Paper Satu", year=2024)])

    summary = run_jobs(session, provider, SINCE, lecturer_id=lecturer.id, now=NOW)
    assert summary.synced == 1


def test_publication_window_handles_leap_day() -> None:
    settings = Settings(publication_window_years=3)
    assert publication_window_start(settings, date(2024, 2, 29)) == date(2021, 2, 28)
    assert publication_window_start(settings, date(2026, 10, 23)) == SINCE


def test_sync_classifies_newly_stored_paper(session: Session) -> None:
    taxonomy = seed_minimal_taxonomy(session)
    make_lecturer(session, "Dosen Satu")
    provider = FakeProvider([RawPaper(title="Klasifikasi data mining untuk UMKM", year=2025)])

    run_jobs(session, provider, SINCE, now=NOW)

    paper = session.exec(select(Paper)).one()
    labels = session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper.id)).all()
    assert [label.topic_id for label in labels] == [taxonomy["Data Mining"].id]


def test_utcnow_is_timezone_aware() -> None:
    assert utcnow().tzinfo is not None
