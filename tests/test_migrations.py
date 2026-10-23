from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_create_core_tables(tmp_path, monkeypatch) -> None:
    database = tmp_path / "migrasi.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    get_settings.cache_clear()
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database}")
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        paper_columns = {column["name"] for column in inspector.get_columns("papers")}
        thesis_columns = {column["name"] for column in inspector.get_columns("theses")}
        engine.dispose()
    finally:
        get_settings.cache_clear()

    assert {
        "lecturers",
        "lecturer_openalex_ids",
        "topics",
        "topic_labs",
        "topic_keywords",
        "papers",
        "paper_topics",
        "paper_duplicates",
        "theses",
        "thesis_supervisors",
        "thesis_topics",
        "import_batches",
        "import_rows",
        "lecturer_aliases",
        "sync_jobs",
        "meta",
        "papers_fts",
    } <= tables
    assert "reviewed_at" in paper_columns
    assert "reviewed_at" in thesis_columns
    assert "import_batch_id" in thesis_columns
