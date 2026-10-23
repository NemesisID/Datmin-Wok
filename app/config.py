"""Pengaturan aplikasi dari environment dan file .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Rekomendasi Pembimbing Skripsi"
    database_path: Path = Path("data/app.db")

    openalex_api_key: str = ""
    openalex_base_url: str = "https://api.openalex.org"

    publication_window_years: int = 3

    enable_scholar_scraper: bool = False

    use_llm: bool = False
    llm_provider: str = ""
    llm_model: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
