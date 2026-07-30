.PHONY: dev test lint

dev:
	uvicorn backend.src.app.main:app --reload

test:
	pytest backend/tests

lint:
	ruff check backend/src
