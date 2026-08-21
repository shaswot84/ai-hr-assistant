FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project || uv sync --frozen

COPY src/ src/
COPY alembic.ini ./
COPY alembic/ alembic/

# Activate the uv-managed virtualenv so `uvicorn`/`python` resolve on PATH.
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

# Optional cross-encoder reranker extra (sentence-transformers + torch, ~2.5GB).
# Disabled/skipped by default to keep image size small and builds fast.
# To enable: uncomment the line below and set RERANKER_ENABLED=true in compose/env.
# RUN uv pip install --python /app/.venv/bin/python --no-cache '.[reranker]'

EXPOSE 8000

# Default: the API. The compose `worker` (ingestion) and `recruitment_worker`
# (outbox) services override this with their respective job-processing
# loops, same image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
