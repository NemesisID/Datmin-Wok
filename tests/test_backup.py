from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.backup import backup_database


def _make_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE contoh (nilai TEXT)")
        connection.execute("INSERT INTO contoh (nilai) VALUES ('isi')")


def test_backup_copies_database_and_creates_monthly_file(tmp_path) -> None:
    source = tmp_path / "app.db"
    _make_database(source)
    result = backup_database(
        source,
        tmp_path / "backups",
        today=date(2026, 10, 23),
        daily_keep=7,
        monthly_keep=1,
    )
    assert result.daily.exists()
    assert result.monthly.exists()
    with sqlite3.connect(result.daily) as connection:
        assert connection.execute("SELECT nilai FROM contoh").fetchone() == ("isi",)
    with sqlite3.connect(result.monthly) as connection:
        assert connection.execute("SELECT nilai FROM contoh").fetchone() == ("isi",)


def test_backup_retention_keeps_daily_and_one_monthly(tmp_path) -> None:
    source = tmp_path / "app.db"
    _make_database(source)
    backup_dir = tmp_path / "backups"
    for day in range(1, 6):
        backup_database(
            source,
            backup_dir,
            today=date(2026, 10, day),
            daily_keep=3,
            monthly_keep=1,
        )
    daily = sorted((backup_dir / "harian").glob("app-*.db"))
    monthly = sorted((backup_dir / "bulanan").glob("app-*.db"))
    assert [path.name for path in daily] == [
        "app-2026-10-03.db",
        "app-2026-10-04.db",
        "app-2026-10-05.db",
    ]
    assert [path.name for path in monthly] == ["app-2026-10.db"]


def test_backup_rejects_missing_database(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "tidak-ada.db", tmp_path / "backups")
