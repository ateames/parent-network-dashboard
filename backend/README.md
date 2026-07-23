# Parent Network Dashboard — backend package

Shared codebase for the FastAPI `api` process and the asyncio `worker` process.

## Database

- SQLAlchemy models live in `app/models/`
- Alembic migrations live in `alembic/versions/`
- The api container entrypoint runs `alembic upgrade head` on startup
- Or apply manually: `make migrate`

See the repository root `Makefile` for Compose and test commands.
