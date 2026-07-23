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
    # Auth: "session" (username/password cookie login) | "token" (API key / bearer).
    unifi_auth_method: str = "session"
    unifi_username: str = ""
    unifi_password: str = ""
    unifi_token: str = ""
    unifi_site: str = "default"
    # Relative paths under unifi_url; `{site}` is substituted from unifi_site.
    unifi_login_path: str = "/api/login"
    unifi_clients_path: str = "/api/s/{site}/stat/sta"
    unifi_devices_path: str = "/api/s/{site}/stat/device"
    unifi_networks_path: str = "/api/s/{site}/rest/networkconf"
    unifi_events_path: str = "/api/s/{site}/stat/event"
    unifi_poll_interval_seconds: int = 60
    unifi_events_limit: int = 100
    unifi_verify_tls: bool = False

    # UniFi syslog listener (read-only; controller pushes lines to this host).
    unifi_syslog_enabled: bool = True
    unifi_syslog_host: str = "0.0.0.0"
    unifi_syslog_port: int = 5514
    # Comma-separated: "udp", "tcp", or "udp,tcp".
    unifi_syslog_protocols: str = "udp,tcp"
    # No lines within this window => source_health degraded for unifi_syslog.
    unifi_syslog_stale_seconds: int = 300
    # How often the worker refreshes unifi_syslog staleness.
    unifi_syslog_health_check_seconds: int = 60

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

    # Device list "online" filter: last_seen within this many seconds.
    device_online_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
