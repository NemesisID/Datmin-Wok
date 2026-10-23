"""Perintah CLI: init-db, hash-password, import-taxonomy."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlmodel import Session

from app.backup import backup_database
from app.config import get_settings
from app.db import get_engine
from app.security import hash_password
from app.taxonomy import import_taxonomy

ROOT = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


def cmd_init_db() -> int:
    run_migrations()
    print(f"Database siap di {get_settings().database_path}")
    return 0


def cmd_hash_password() -> int:
    password = getpass.getpass("Kata sandi admin: ")
    confirmation = getpass.getpass("Ulangi kata sandi: ")
    if password != confirmation:
        print("Kata sandi tidak sama.")
        return 1
    print()
    print("Tempel baris ini ke .env:")
    print(f"ADMIN_PASSWORD_HASH={hash_password(password)}")
    return 0


def cmd_import_taxonomy(path: str) -> int:
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        print(f"Berkas tidak ditemukan: {source}")
        return 1
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    try:
        with Session(get_engine()) as session:
            summary = import_taxonomy(session, data)
            session.commit()
    except ValueError as error:
        print(f"Seed ditolak: {error}")
        return 1

    print(f"Topik baru: {summary.topics_created}, diperbarui: {summary.topics_updated}")
    print(
        f"Kata kunci baru: {summary.keywords_added}, diperbarui: {summary.keywords_updated}, "
        f"dihapus: {summary.keywords_removed}"
    )
    print(f"Lab ditambah: {summary.labs_added}, dihapus: {summary.labs_removed}")
    print(f"taxonomy_version: {summary.version}")
    return 0


def cmd_backup() -> int:
    settings = get_settings()
    try:
        result = backup_database(
            settings.database_path,
            settings.backup_dir,
            daily_keep=settings.backup_daily_keep,
            monthly_keep=settings.backup_monthly_keep,
        )
    except (FileNotFoundError, RuntimeError) as error:
        print(str(error))
        return 1
    print(f"Backup harian: {result.daily}")
    print(f"Backup bulanan: {result.monthly}")
    if result.removed:
        print(f"Backup lama dihapus: {len(result.removed)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Jalankan migrasi database.")
    subparsers.add_parser("hash-password", help="Buat hash kata sandi admin.")
    import_parser = subparsers.add_parser("import-taxonomy", help="Impor seed taksonomi YAML.")
    import_parser.add_argument("path", nargs="?", default="seeds/taxonomy.yaml")
    subparsers.add_parser("backup", help="Buat backup SQLite dan bersihkan backup lama.")

    args = parser.parse_args(argv)
    if args.command == "init-db":
        return cmd_init_db()
    if args.command == "hash-password":
        return cmd_hash_password()
    if args.command == "import-taxonomy":
        return cmd_import_taxonomy(args.path)
    if args.command == "backup":
        return cmd_backup()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
