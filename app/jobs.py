"""CLI job: python -m app.jobs sync [--force] [--lecturer ID] atau reclassify."""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from app.classify import Classifier, reclassify_papers, reclassify_theses
from app.config import get_settings
from app.db import get_engine
from app.models import SyncJob, utcnow
from app.providers.openalex import OpenAlexProvider, build_client
from app.sync import fail_stale_jobs, publication_window_start, run_jobs
from app.taxonomy import get_taxonomy_version


def cmd_sync(force: bool, lecturer_id: int | None) -> int:
    settings = get_settings()
    since = publication_window_start(settings)
    client = build_client(settings.openalex_base_url, settings.openalex_api_key)
    try:
        with Session(get_engine()) as session:
            summary = run_jobs(
                session,
                OpenAlexProvider(client),
                since,
                force=force,
                lecturer_id=lecturer_id,
            )
    finally:
        client.close()

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
    with Session(get_engine()) as session:
        fail_stale_jobs(session)
        pending = session.exec(
            select(SyncJob).where(SyncJob.source == "reclassify", SyncJob.status == "pending")
        ).all()
        job_ids = [job.id for job in pending]
        for job in pending:
            job.status = "running"
            job.attempts += 1
            job.started_at = utcnow()
            session.add(job)
        session.commit()

        try:
            classifier = Classifier.from_session(session)
            version = get_taxonomy_version(session)
            papers = reclassify_papers(session, classifier=classifier, version=version)
            theses = reclassify_theses(session, classifier=classifier, version=version)
        except Exception as error:
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

        for job_id in job_ids:
            job = session.get(SyncJob, job_id)
            if job is not None:
                job.status = "done"
                job.finished_at = utcnow()
                job.new_papers = papers.labels + theses.labels
                session.add(job)
        session.commit()

    print(f"taxonomy_version: {version}")
    print(
        f"Paper diperiksa: {papers.scanned}, berlabel: {papers.labeled}, "
        f"label dibuat: {papers.labels}, dilewati karena review: {papers.skipped_reviewed}"
    )
    print(
        f"Skripsi diperiksa: {theses.scanned}, berlabel: {theses.labeled}, "
        f"label dibuat: {theses.labels}, dilewati karena review: {theses.skipped_reviewed}"
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
