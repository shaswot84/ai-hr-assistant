from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.knowledge import router as knowledge_router
from app.api.routes import auth as auth_router
from app.api.routes import recruitment as recruitment_router
from app.api.routes import settings as settings_router
from app.config.settings import get_settings
from app.db.sync_session import init_db
from app.integrations.object_store import SyncS3ObjectStore

log = logging.getLogger("app")


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
            store = SyncS3ObjectStore()
            store.ensure_bucket()
        except Exception as err:  # noqa: BLE001 - don't crash API if MinIO is briefly unavailable
            log.warning("MinIO bucket setup skipped: %s", err)
    yield


app = FastAPI(title="AI HR Assistant", lifespan=lifespan)

# The Next.js frontend (:3000) calls this API directly from the browser, so
# CORS must allow it. Origins come from CORS_ALLOW_ORIGINS (comma-separated,
# default "*" — fine locally since no cookies/credentials are used).
_origins = [o.strip() for o in get_settings().cors.allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
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
app.include_router(knowledge_router)


@app.get("/health")
async def health():
    """Liveness probe returning a simple status payload."""
    return {"status": "ok"}
