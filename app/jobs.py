"""CLI job: python -m app.jobs sync [--force] [--lecturer ID] atau reclassify."""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from app.classify import (
    Classifier,
    ReclassifyStats,
    affected_ids,
    reclassify_papers,
    reclassify_theses,
)
from app.config import get_settings
from app.db import get_engine
from app.llm import build_llm_provider
from app.models import SyncJob, utcnow
from app.providers.openalex import OpenAlexProvider, build_client
from app.sync import fail_stale_jobs, publication_window_start, run_jobs
from app.taxonomy import get_taxonomy_version

RECLASSIFY_SOURCE = "reclassify"


def _topic_from_source(source: str) -> int | None:
    if source == RECLASSIFY_SOURCE:
        return None
    prefix = f"{RECLASSIFY_SOURCE}:"
    if not source.startswith(prefix):
        raise ValueError(f"Sumber job klasifikasi tidak dikenal: {source}")
    try:
        return int(source[len(prefix) :])
    except ValueError as error:
        raise ValueError(f"ID topik pada job tidak valid: {source}") from error


def _merge_stats(total: ReclassifyStats, item: ReclassifyStats) -> None:
    total.scanned += item.scanned
    total.labeled += item.labeled
    total.labels += item.labels
    total.skipped_reviewed += item.skipped_reviewed
    total.llm_cached += item.llm_cached
    total.llm_requests += item.llm_requests
    total.llm_labeled += item.llm_labeled


def cmd_sync(force: bool, lecturer_id: int | None) -> int:
    settings = get_settings()
    since = publication_window_start(settings)
    try:
        llm = build_llm_provider(settings)
    except ValueError as error:
        print(f"Konfigurasi LLM tidak valid: {error}")
        return 1
    try:
        client = build_client(settings.openalex_base_url, settings.openalex_api_key)
        try:
            with Session(get_engine()) as session:
                summary = run_jobs(
                    session,
                    OpenAlexProvider(client),
                    since,
                    force=force,
                    lecturer_id=lecturer_id,
                    llm=llm,
                    llm_batch_size=settings.llm_batch_size,
                )
        finally:
            client.close()
    finally:
        if llm is not None:
            llm.close()

    print(f"Jendela publikasi sejak {since.isoformat()}")
    print(
        f"Dosen disinkronkan: {summary.synced}, dilewati: {summary.skipped}, "
        f"gagal: {summary.failed}"
    )
    print(
        f"Paper baru: {summary.new_papers}, diperbarui: {summary.merged}, "
        f"kandidat duplikat: {summary.duplicates}"
    )
    print(f"Kredit OpenAlex terpakai: {summary.credits:.4f}")
    if summary.failed:
        print("Ada job gagal. Periksa kolom error di halaman dosen.")
        return 1
    return 0


def cmd_reclassify() -> int:
    settings = get_settings()
    with Session(get_engine()) as session:
        fail_stale_jobs(session)
        pending = session.exec(
            select(SyncJob).where(
                SyncJob.source.like(f"{RECLASSIFY_SOURCE}%"),
                SyncJob.status == "pending",
            )
        ).all()
        job_ids = [job.id for job in pending]
        for job in pending:
            job.status = "running"
            job.attempts += 1
            job.started_at = utcnow()
            session.add(job)
        session.commit()

        provider = None
        try:
            provider = build_llm_provider(settings)
            classifier = Classifier.from_session(session)
            version = get_taxonomy_version(session)

            paper_ids: list[int] | None = None
            thesis_ids: list[int] | None = None
            mode = "semua"
            if pending:
                topic_ids: set[int] = set()
                global_scope = False
                for job in pending:
                    topic_id = _topic_from_source(job.source)
                    if topic_id is None:
                        global_scope = True
                    else:
                        topic_ids.add(topic_id)
                if not global_scope:
                    selected_papers: set[int] = set()
                    selected_theses: set[int] = set()
                    for topic_id in sorted(topic_ids):
                        paper_scope, thesis_scope = affected_ids(
                            session, topic_id, classifier=classifier
                        )
                        selected_papers.update(paper_scope)
                        selected_theses.update(thesis_scope)
                    paper_ids = sorted(selected_papers)
                    thesis_ids = sorted(selected_theses)
                    mode = f"{len(paper_ids)} paper, {len(thesis_ids)} skripsi"

            papers = reclassify_papers(
                session,
                paper_ids=paper_ids,
                classifier=classifier,
                version=version,
                llm=provider,
                llm_batch_size=settings.llm_batch_size,
            )
            theses = reclassify_theses(
                session,
                thesis_ids=thesis_ids,
                classifier=classifier,
                version=version,
            )
        except Exception as error:
            session.rollback()
            for job_id in job_ids:
                job = session.get(SyncJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.finished_at = utcnow()
                    job.error = str(error)[:500]
                    session.add(job)
            session.commit()
            print(f"Klasifikasi ulang gagal: {error}")
            return 1
        finally:
            if provider is not None:
                provider.close()

        total = ReclassifyStats()
        _merge_stats(total, papers)
        _merge_stats(total, theses)
        for job_id in job_ids:
            job = session.get(SyncJob, job_id)
            if job is not None:
                job.status = "done"
                job.finished_at = utcnow()
                job.new_papers = total.labels
                session.add(job)
        session.commit()

    print(f"taxonomy_version: {version}")
    print(f"Cakupan: {mode}")
    print(
        f"Paper diperiksa: {papers.scanned}, berlabel: {papers.labeled}, "
        f"label dibuat: {papers.labels}, dilewati karena review: {papers.skipped_reviewed}"
    )
    print(
        f"Skripsi diperiksa: {theses.scanned}, berlabel: {theses.labeled}, "
        f"label dibuat: {theses.labels}, dilewati karena review: {theses.skipped_reviewed}"
    )
    if provider is not None:
        print(
            f"LLM: cache={papers.llm_cached}, request={papers.llm_requests}, "
            f"paper berlabel LLM={papers.llm_labeled}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync", help="Sinkronkan publikasi dari OpenAlex.")
    sync_parser.add_argument(
        "--force", action="store_true", help="Abaikan jeda 7 hari sejak sinkronisasi terakhir."
    )
    sync_parser.add_argument("--lecturer", type=int, help="Batasi ke satu ID dosen.")
    subparsers.add_parser("reclassify", help="Klasifikasi ulang paper dan skripsi.")

    args = parser.parse_args(argv)
    if args.command == "sync":
        return cmd_sync(args.force, args.lecturer)
    if args.command == "reclassify":
        return cmd_reclassify()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
