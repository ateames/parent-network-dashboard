"""FastAPI application entrypoint."""

from __future__ import annotations

import platform
import sys

from fastapi import FastAPI

from app import __version__ as package_version
from app.config import settings

app = FastAPI(title="Parent Network Dashboard API", version=settings.app_version)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/version")
async def version() -> dict[str, str]:
    """Return app version plus git-independent build metadata."""
    return {
        "version": settings.app_version or package_version,
        "build_id": settings.build_id,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
