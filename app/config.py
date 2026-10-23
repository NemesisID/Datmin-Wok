"""Pengaturan aplikasi dari environment dan file .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Rekomendasi Pembimbing Skripsi"
    database_path: Path = Path("data/app.db")
    backup_dir: Path = Path("data/backups")
    backup_daily_keep: int = 7
    backup_monthly_keep: int = 1

    openalex_api_key: str = ""
    openalex_base_url: str = "https://api.openalex.org"

    publication_window_years: int = 3
    recency_half_life_years: float = 2.0
    thesis_lambda: float = 1.5
    stale_days: int = 90

    enable_scholar_scraper: bool = False

    use_llm: bool = False
    llm_provider: str = ""
    llm_model: str = ""

    admin_username: str = "admin"
    admin_password_hash: str = ""
    secret_key: str = ""
    cookie_secure: bool = False
    session_max_age_seconds: int = 8 * 60 * 60
    login_max_attempts: int = 5
    login_window_seconds: int = 15 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
