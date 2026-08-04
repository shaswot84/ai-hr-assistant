.PHONY: dev test lint

PYTHON   := backend/.venv/bin/python
PYTEST   := backend/.venv/bin/pytest
RUFF     := backend/.venv/bin/ruff
UVICORN  := backend/.venv/bin/uvicorn

dev:
	cd backend && .venv/bin/uvicorn app.main:app --reload

test:
	$(PYTEST) backend/tests

lint:
	$(RUFF) check backend/src
