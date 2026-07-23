"""Worker process entrypoint — heartbeat loop; no ingestion yet."""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import text

from app.db import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

HEARTBEAT_INTERVAL_SECONDS = 30


async def connect_db() -> None:
    """Verify PostgreSQL connectivity on startup."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database connection ok")


async def run() -> None:
    try:
        await connect_db()
        while True:
            logger.info("worker alive")
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
