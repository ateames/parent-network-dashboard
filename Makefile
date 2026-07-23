# Parent Network Dashboard — common commands
#
# Prerequisites: Docker with Compose v2 (`docker compose`).
# First run:  cp infra/.env.example infra/.env

COMPOSE := docker compose -f infra/docker-compose.yml --env-file infra/.env
BACKEND  := backend

.PHONY: up down logs test migrate

## Build and start db, api, worker, and frontend in the background
up:
	@test -f infra/.env || (echo "Missing infra/.env — copy from infra/.env.example" && exit 1)
	$(COMPOSE) up -d --build

## Stop containers (named volume kept)
down:
	$(COMPOSE) down

## Follow logs for all services
logs:
	$(COMPOSE) logs -f

## Apply Alembic migrations (alembic upgrade head) against the Compose db
migrate:
	@test -f infra/.env || (echo "Missing infra/.env — copy from infra/.env.example" && exit 1)
	$(COMPOSE) run --rm --entrypoint alembic api upgrade head

## Run backend pytest (inside a one-off api container; starts db)
test:
	@test -f infra/.env || (echo "Missing infra/.env — copy from infra/.env.example" && exit 1)
	$(COMPOSE) run --rm --build --entrypoint pytest api -q
