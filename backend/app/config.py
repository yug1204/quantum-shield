from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite for quick local dev; docker-compose overrides this with PostgreSQL.
    database_url: str = "sqlite:///./quantum_shield.db"
    repos_dir: Path = Path("data/repos")
    max_upload_mb: int = 50


settings = Settings()
