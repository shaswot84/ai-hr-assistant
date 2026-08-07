FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY alembic/ alembic/
COPY alembic.ini .
COPY src/ src/

RUN pip install --no-cache-dir '.[reranker]'

EXPOSE 8000

# Default: the API. The compose `worker` service overrides this with the
# ingestion worker loop (same image, different entrypoint).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
