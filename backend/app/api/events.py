"""Live event stream: SSE + recent backfill."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.events.bus import get_event_bus
from app.events.store import list_recent_events
from app.schemas.events import StreamEventListOut, StreamEventOut

router = APIRouter(tags=["events"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_frame(event: StreamEventOut) -> str:
    payload = event.model_dump(mode="json")
    data = json.dumps(payload, separators=(",", ":"), default=str)
    return f"id: {event.id}\nevent: stream\ndata: {data}\n\n"


@router.get("/api/events/recent", response_model=StreamEventListOut)
async def recent_events(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> StreamEventListOut:
    """Backfill the latest N meaningful events (severity, then time)."""
    items = await list_recent_events(session, limit=limit)
    return StreamEventListOut(items=items, count=len(items))


@router.get("/api/events/stream")
async def stream_events(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of meaningful household events."""
    bus = get_event_bus()

    async def event_generator():
        queue = bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # Keep-alive so proxies / browsers do not idle-close.
                    yield ": keepalive\n\n"
                    continue
                yield _sse_frame(event)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
