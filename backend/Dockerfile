# arm64-friendly image for Raspberry Pi (and amd64 via multi-arch base).
# Build context: repository root (see infra/docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for asyncpg runtime; keep image slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
COPY backend/worker.py ./
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/tests ./tests
COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
COPY fixtures /fixtures

RUN chmod +x /docker-entrypoint.sh \
    && pip install --upgrade pip \
    && pip install ".[dev]"

EXPOSE 8000 5514/udp 5514/tcp
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
