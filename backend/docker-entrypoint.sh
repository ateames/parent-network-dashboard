#!/bin/sh
# Run pending Alembic migrations, then exec the container command.
set -e

if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  echo "Running alembic upgrade head..."
  alembic upgrade head
fi

exec "$@"
