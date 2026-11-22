SHELL := /bin/sh

BACKEND_DIR := backend
FRONTEND_DIR := frontend
UV := uv --directory $(BACKEND_DIR)
COMPOSE := docker compose --env-file $(BACKEND_DIR)/.env
MESSAGE ?= schema change

.PHONY: install dev front dev-down up test lint typecheck check migration-generate migration-migrate migration-push db-generate db-migrate db-push openapi

install:
	$(UV) sync
	cd $(FRONTEND_DIR) && pnpm install

# Backend + Postgres + Mongo in Docker; run the frontend with `make front`.
dev:
	$(COMPOSE) up --build backend

front:
	cd $(FRONTEND_DIR) && pnpm dev

dev-down:
	$(COMPOSE) down

# Full containerized stack (frontend + backend + db + mongo).
up:
	$(COMPOSE) up --build -d

# Backend tests need Postgres + Mongo running (`make dev`).
test:
	$(UV) run pytest
	cd $(FRONTEND_DIR) && pnpm test

lint:
	$(UV) run flake8
	cd $(FRONTEND_DIR) && pnpm lint

typecheck:
	$(UV) run mypy .
	cd $(FRONTEND_DIR) && pnpm typecheck

# Everything CI runs.
check: lint typecheck test

# Generate a new revision from SQLAlchemy metadata.
migration-generate db-generate:
	$(UV) run alembic revision --autogenerate -m "$(MESSAGE)"

# Apply all committed revisions that are not yet applied.
migration-migrate db-migrate:
	$(UV) run alembic upgrade head

# Generate a revision and immediately apply it.
migration-push db-push:
	$(MAKE) migration-generate MESSAGE="$(MESSAGE)"
	$(MAKE) migration-migrate

# Regenerate docs/api/openapi.json from the FastAPI app.
openapi:
	$(UV) run python -m scripts.export_openapi
