"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Placeholders are fine until real hosts/creds are wired."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://parent:parent@localhost:5432/parent_network"
    )

    pihole_url: str = "http://pihole.local"
    unifi_url: str = "https://unifi.local"

    admin_username: str = "admin"
    admin_password: str = "changeme"
    admin_token: str = "changeme"

    # Git-independent identity for /version (override at build/deploy time).
    app_version: str = "0.1.0"
    build_id: str = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
