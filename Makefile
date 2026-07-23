# Parent Network Dashboard — common commands
#
# Prerequisites: Docker with Compose v2 (`docker compose`).
# First run:  cp infra/.env.example infra/.env

COMPOSE := docker compose -f infra/docker-compose.yml --env-file infra/.env
BACKEND  := backend

.PHONY: up down logs test

## Build and start db, api, and worker in the background
up:
	@test -f infra/.env || (echo "Missing infra/.env — copy from infra/.env.example" && exit 1)
	$(COMPOSE) up -d --build

## Stop containers (named volume kept)
down:
	$(COMPOSE) down

## Follow logs for all services
logs:
	$(COMPOSE) logs -f

## Run backend pytest (inside a one-off api container)
test:
	@test -f infra/.env || (echo "Missing infra/.env — copy from infra/.env.example" && exit 1)
	$(COMPOSE) run --rm --no-deps --entrypoint pytest api -q
