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

# Optional cross-encoder reranker extra (sentence-transformers + torch,
# ~2.5GB) — installed separately from the locked base deps so uv.lock
# doesn't need to pin the full torch dependency tree. Install into the
# uv-managed venv explicitly: that venv has no pip of its own, and a bare
# `pip install` would target the system interpreter instead.
RUN uv pip install --python /app/.venv/bin/python --no-cache '.[reranker]'

EXPOSE 8000

# Default: the API. The compose `worker` (ingestion) and `recruitment_worker`
# (outbox) services override this with their respective job-processing
# loops, same image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
