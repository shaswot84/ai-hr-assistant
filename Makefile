.PHONY: help up fresh down start stop restart logs ps build setup migrate seed test lint dev

DOCKER := docker compose

help:
	@echo "AI HR Assistant - Makefile"
	@echo ""
	@echo "Quick start (fresh checkout):"
	@echo "  make up          One-command start: copies .env if missing, builds,"
	@echo "                   starts infra, runs Alembic migrations, starts the"
	@echo "                   app services, and seeds demo data"
	@echo "  make fresh       Clean slate: stop and remove containers + volumes,"
	@echo "                   then run 'make up' from scratch"
	@echo ""
	@echo "Run / stop:"
	@echo "  make stop        Pause all containers (keeps them)"
	@echo "  make start       Resume the same containers (no rebuild)"
	@echo "  make restart     Restart all services"
	@echo "  make down        Stop AND remove containers (data kept)"
	@echo "  make ps          Show service status"
	@echo "  make logs        Tail logs from all services"
	@echo "  make build       Rebuild images"
	@echo ""
	@echo "Setup / data:"
	@echo "  make setup       Copy .env.example -> .env (only if .env missing)"
	@echo "  make migrate     Run Alembic migrations against the running database"
	@echo "  make seed        Seed demo users, sample vacancies, and leave data"
	@echo ""
	@echo "Local backend (no Docker):"
	@echo "  make dev         Run backend via uvicorn with reload"
	@echo ""
	@echo "Quality:"
	@echo "  make test        Run pytest"
	@echo "  make lint        Run ruff check"

# ---- Quick start -------------------------------------------------------

# Fresh checkout: ensure .env exists, bring up infra, migrate, then the app services, then seed.
up: setup
	$(DOCKER) build
	$(DOCKER) up -d postgres minio mailpit
	$(MAKE) migrate
	$(DOCKER) up -d backend worker recruitment_worker frontend
	@echo "Stack is up:"
	@echo "  Frontend (candidate/manager/employee portals): http://localhost:3000"
	@echo "  Backend  (API docs):                           http://localhost:8000/docs"
	@echo "  Mailpit  (dev email):                          http://localhost:8025"
	@echo "  MinIO    (console):                             http://localhost:9001"
	@echo ""
	$(MAKE) seed

# Clean slate: stop and remove containers + volumes (fresh DB/MinIO/node_modules), then bring the stack up.
fresh:
	$(DOCKER) down -v
	$(MAKE) up

# Copy .env.example to .env only if .env does not already exist.
setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; else echo ".env already exists - keeping it"; fi

# Apply Alembic migrations (the real schema-management path — not create_all()).
migrate:
	@echo "Running Alembic migrations..."
	$(DOCKER) run --rm backend alembic upgrade head

seed:
	@echo "Seeding demo data (idempotent)..."
	@cd backend && PYTHONPATH=src .venv/bin/python -m app.db.seed 2>/dev/null || docker compose exec backend python -m app.db.seed

# ---- Docker Compose workflow ------------------------------------------

down:
	$(DOCKER) down

start:
	$(DOCKER) start

stop:
	$(DOCKER) stop

restart:
	$(DOCKER) restart

ps:
	$(DOCKER) ps

logs:
	$(DOCKER) logs -f --tail=100

build:
	$(DOCKER) build

# ---- Local backend ----------------------------------------------------

dev:
	cd backend && .venv/bin/uvicorn app.main:app --reload

# ---- Quality ----------------------------------------------------------

test:
	cd backend && .venv/bin/python -m pytest tests

lint:
	cd backend && .venv/bin/python -m ruff check src