"""Backup SQLite dengan VACUUM INTO dan retensi harian/bulanan."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DAILY_PREFIX = "app-"
DAILY_SUFFIX = ".db"


@dataclass
class BackupResult:
    daily: Path
    monthly: Path
    removed: list[Path] = field(default_factory=list)


def _vacuum_into(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    destination = target.resolve().as_posix().replace("'", "''")
    try:
        with sqlite3.connect(source) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(f"VACUUM INTO '{destination}'")
    except sqlite3.Error as error:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Backup gagal: {error}") from error


def _prune(folder: Path, keep: int) -> list[Path]:
    files = sorted(folder.glob(f"{DAILY_PREFIX}*{DAILY_SUFFIX}"), key=lambda item: item.name)
    doomed = files if keep <= 0 else files[:-keep]
    for path in doomed:
        path.unlink(missing_ok=True)
    return doomed


def backup_database(
    database: Path,
    backup_dir: Path,
    *,
    today: date | None = None,
    daily_keep: int = 7,
    monthly_keep: int = 1,
) -> BackupResult:
    source = Path(database)
    if not source.exists():
        raise FileNotFoundError(f"Database tidak ditemukan: {source}")

    today = today or date.today()
    daily_dir = Path(backup_dir) / "harian"
    monthly_dir = Path(backup_dir) / "bulanan"
    daily = daily_dir / f"{DAILY_PREFIX}{today.isoformat()}{DAILY_SUFFIX}"
    monthly = monthly_dir / f"{DAILY_PREFIX}{today.strftime('%Y-%m')}{DAILY_SUFFIX}"

    _vacuum_into(source, daily)
    monthly.parent.mkdir(parents=True, exist_ok=True)
    monthly.unlink(missing_ok=True)
    shutil.copy2(daily, monthly)

    removed = _prune(daily_dir, daily_keep)
    removed.extend(_prune(monthly_dir, monthly_keep))
    return BackupResult(daily=daily, monthly=monthly, removed=removed)
