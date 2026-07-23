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
    # Auth: "none" | "password" (Pi-hole v6 SID session) | "token" (legacy auth= param).
    pihole_auth_method: str = "password"
    pihole_password: str = ""
    pihole_token: str = ""
    # Relative paths under pihole_url (custom proxies / API versions).
    pihole_queries_path: str = "/api/queries"
    pihole_auth_path: str = "/api/auth"
    pihole_poll_interval_seconds: int = 60
    pihole_query_length: int = 100
    pihole_verify_tls: bool = False

    unifi_url: str = "https://unifi.local"

    admin_username: str = "admin"
    admin_password: str = "changeme"
    admin_token: str = "changeme"

    # Git-independent identity for /version (override at build/deploy time).
    app_version: str = "0.1.0"
    build_id: str = "dev"

    # Source health: success older than this => degraded.
    source_health_stale_seconds: int = 300
    # Source health: this many consecutive failures => down.
    source_health_max_failures: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
