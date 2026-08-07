from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth as auth_router
from app.api.routes import recruitment as recruitment_router
from app.api.routes import settings as settings_router
from app.config.settings import get_settings
from app.db.sync_session import init_db
from app.integrations.object_store import ObjectStore

log = logging.getLogger("app")

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown hook: dev-fallback table creation + ensure the MinIO bucket exists.

    Real schema management is Alembic (`make migrate`), not `init_db()` —
    see `db.sync_session.init_db` for why it's still called here.
    """
    init_db()
    settings = get_settings()
    if settings.minio.auto_init:
        try:
            store = ObjectStore()
            store.ensure_bucket()
        except Exception as err:  # noqa: BLE001 - don't crash API if MinIO is briefly unavailable
            log.warning("MinIO bucket setup skipped: %s", err)
    yield


app = FastAPI(title="AI HR Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # the resume download endpoint sets the real filename (with its actual
    # extension) via Content-Disposition; browsers hide response headers
    # from JS on cross-origin fetches unless explicitly exposed here.
    expose_headers=["Content-Disposition"],
)

app.include_router(auth_router.router)
app.include_router(recruitment_router.router)
app.include_router(settings_router.router)


@app.get("/health")
async def health():
    """Liveness probe returning a simple status payload."""
    return {"status": "ok"}
