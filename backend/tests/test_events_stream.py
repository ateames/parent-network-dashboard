"""Live event bus, SSE delivery, and recent backfill ordering."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import get_session
from app.events.bus import get_event_bus, reset_event_bus
from app.events.publish import publish_stream_event
from app.main import app
from app.models.enums import FindingSeverity, StreamEventKind
from app.schemas.events import StreamEventOut


@pytest.fixture(autouse=True)
def _fresh_event_bus() -> None:
    reset_event_bus()


@pytest_asyncio.fixture
async def api_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(
        bind=migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


def _parse_sse_data_lines(chunk: str) -> list[dict]:
    events: list[dict] = []
    data_lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "" and data_lines:
            payload = "\n".join(data_lines)
            events.append(json.loads(payload))
            data_lines = []
    if data_lines:
        events.append(json.loads("\n".join(data_lines)))
    return events


@pytest.mark.asyncio
async def test_publish_delivers_to_sse_client(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Publishing an event delivers it to an attached SSE client."""
    received: asyncio.Future[dict] = asyncio.get_running_loop().create_future()

    async def _reader() -> None:
        async with api_client.stream("GET", "/api/events/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            buffer = ""
            async for text in response.aiter_text():
                buffer += text
                for event in _parse_sse_data_lines(buffer):
                    if not received.done():
                        received.set_result(event)
                    return

    reader = asyncio.create_task(_reader())
    bus = get_event_bus()
    for _ in range(100):
        if bus.subscriber_count > 0:
            break
        await asyncio.sleep(0.01)
    else:
        reader.cancel()
        pytest.fail("SSE client did not subscribe in time")

    published = await publish_stream_event(
        db_session,
        kind=StreamEventKind.BLOCKED_QUERY_BURST,
        severity=FindingSeverity.MEDIUM,
        summary="Several blocked DNS lookups attributed to Alex in 15 minutes.",
        occurred_at=datetime(2024, 7, 23, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()

    event = await asyncio.wait_for(received, timeout=2.0)
    assert event["id"] == str(published.id)
    assert event["kind"] == StreamEventKind.BLOCKED_QUERY_BURST.value
    assert event["severity"] == FindingSeverity.MEDIUM.value
    assert "blocked DNS lookups" in event["summary"]
    assert event["finding_id"] is None

    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


@pytest.mark.asyncio
async def test_recent_events_ordered_by_severity_then_time(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Recent backfill returns the latest N ordered by severity, then time."""
    base = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    await publish_stream_event(
        db_session,
        kind=StreamEventKind.NEW_DEVICE_JOINED,
        severity=FindingSeverity.INFO,
        summary="A new device joined the network (tablet).",
        occurred_at=base + timedelta(minutes=5),
    )
    await publish_stream_event(
        db_session,
        kind=StreamEventKind.SOURCE_DATA_LOSS,
        severity=FindingSeverity.HIGH,
        summary="Loss of Pi-hole data: 3 consecutive failure(s)",
        source="pihole_api",
        occurred_at=base,
    )
    await publish_stream_event(
        db_session,
        kind=StreamEventKind.UNKNOWN_DEVICE_ONLINE,
        severity=FindingSeverity.MEDIUM,
        summary="An unrecognized device was seen online.",
        occurred_at=base + timedelta(minutes=10),
    )
    await publish_stream_event(
        db_session,
        kind=StreamEventKind.DNS_VOLUME_INCREASE,
        severity=FindingSeverity.MEDIUM,
        summary="DNS lookup volume rose sharply for a device.",
        occurred_at=base + timedelta(minutes=1),
    )
    await db_session.commit()

    resp = await api_client.get("/api/events/recent", params={"limit": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    kinds = [item["kind"] for item in body["items"]]
    severities = [item["severity"] for item in body["items"]]

    # High first, then newer medium before older medium; info dropped by limit.
    assert severities[0] == FindingSeverity.HIGH.value
    assert kinds[0] == StreamEventKind.SOURCE_DATA_LOSS.value
    assert severities[1] == FindingSeverity.MEDIUM.value
    assert kinds[1] == StreamEventKind.UNKNOWN_DEVICE_ONLINE.value
    assert severities[2] == FindingSeverity.MEDIUM.value
    assert kinds[2] == StreamEventKind.DNS_VOLUME_INCREASE.value

    full = await api_client.get("/api/events/recent", params={"limit": 50})
    assert full.json()["count"] == 4
    assert full.json()["items"][-1]["kind"] == StreamEventKind.NEW_DEVICE_JOINED.value


@pytest.mark.asyncio
async def test_bus_recent_matches_severity_priority() -> None:
    bus = get_event_bus()
    now = datetime(2024, 7, 23, 12, 0, tzinfo=UTC)
    low = StreamEventOut(
        id=uuid4(),
        logic_version="stream_events.v1",
        kind=StreamEventKind.NEW_DEVICE_JOINED,
        severity=FindingSeverity.LOW,
        summary="low",
        occurred_at=now + timedelta(hours=1),
        created_at=now,
    )
    high = StreamEventOut(
        id=uuid4(),
        logic_version="stream_events.v1",
        kind=StreamEventKind.SOURCE_DATA_LOSS,
        severity=FindingSeverity.HIGH,
        summary="high",
        occurred_at=now,
        created_at=now,
    )
    bus.publish(low)
    bus.publish(high)
    recent = bus.recent(limit=2)
    assert recent[0].severity == FindingSeverity.HIGH
    assert recent[1].severity == FindingSeverity.LOW
