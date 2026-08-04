.PHONY: help up down start stop restart logs ps build setup seed test lint dev

DOCKER := docker compose

help:
	@echo "AI HR Assistant - Makefile"
	@echo ""
	@echo "Quick start (fresh checkout):"
	@echo "  make up          One-command start: copies .env if missing, builds,"
	@echo "                   starts the full stack, and seeds demo data"
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
	@echo "  make seed        Seed demo manager + sample vacancy"
	@echo ""
	@echo "Local backend (no Docker):"
	@echo "  make dev         Run backend via uvicorn with reload"
	@echo ""
	@echo "Quality:"
	@echo "  make test        Run pytest"
	@echo "  make lint        Run ruff check"

# ---- Quick start -------------------------------------------------------

# Fresh checkout: ensure .env exists, build & start everything, then seed.
up: setup
	$(DOCKER) up -d --build
	@echo "Stack is up:"
	@echo "  Frontend (candidate/manager portals): http://localhost:3000"
	@echo "  Backend  (API docs):                  http://localhost:8000/docs"
	@echo "  Mailpit  (dev email):                 http://localhost:8025"
	@echo "  MinIO    (console):                   http://localhost:9001"
	@echo "  Keycloak:                             http://localhost:8080"
	@echo ""
	$(MAKE) seed

# Copy .env.example to .env only if .env does not already exist.
setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; else echo ".env already exists - keeping it"; fi

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