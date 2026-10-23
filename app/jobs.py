"""CLI job: python -m app.jobs sync [--force] [--lecturer ID]."""

from __future__ import annotations

import argparse

from sqlmodel import Session

from app.config import get_settings
from app.db import get_engine
from app.providers.openalex import OpenAlexProvider, build_client
from app.sync import publication_window_start, run_jobs


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync", help="Sinkronkan publikasi dari OpenAlex.")
    sync_parser.add_argument(
        "--force", action="store_true", help="Abaikan jeda 7 hari sejak sinkronisasi terakhir."
    )
    sync_parser.add_argument("--lecturer", type=int, help="Batasi ke satu ID dosen.")

    args = parser.parse_args(argv)
    if args.command == "sync":
        return cmd_sync(args.force, args.lecturer)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
