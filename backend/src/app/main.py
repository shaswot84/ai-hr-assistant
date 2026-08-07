from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.knowledge import router as knowledge_router
from app.config.settings import get_settings

app = FastAPI(title="AI HR Assistant")

# The Next.js frontend (:3000) calls this API directly from the browser, so
# CORS must allow it. Origins come from CORS_ALLOW_ORIGINS (comma-separated,
# default "*" — fine locally since no cookies/credentials are used).
_origins = [
    o.strip() for o in get_settings().cors.allow_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(knowledge_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
