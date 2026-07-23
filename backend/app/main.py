"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import platform
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__ as package_version
from app.api.activity import router as activity_router
from app.api.correlation import router as correlation_router
from app.api.dashboard import router as dashboard_router
from app.api.devices import router as devices_router
from app.api.events import router as events_router
from app.api.findings import router as findings_router
from app.api.people import router as people_router
from app.api.sources import router as sources_router
from app.api.suppressions import router as suppressions_router
from app.config import settings
from app.events.poller import stream_event_poll_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = asyncio.Event()
    poller: asyncio.Task[None] | None = None
    if settings.stream_event_poll_enabled:
        poller = asyncio.create_task(
            stream_event_poll_loop(
                interval_seconds=settings.stream_event_poll_interval_seconds,
                stop_event=stop,
            )
        )
    try:
        yield
    finally:
        stop.set()
        if poller is not None:
            await poller


app = FastAPI(
    title="Parent Network Dashboard API",
    version=settings.app_version,
    lifespan=lifespan,
)
app.include_router(sources_router)
app.include_router(devices_router)
app.include_router(people_router)
app.include_router(correlation_router)
app.include_router(activity_router)
app.include_router(findings_router)
app.include_router(suppressions_router)
app.include_router(dashboard_router)
app.include_router(events_router)


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
