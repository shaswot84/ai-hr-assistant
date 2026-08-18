#!/usr/bin/env python3
"""End-to-end smoke test for the ingestion pipeline + Knowledge Service.

Hits the running FastAPI (http://localhost:8000 by default):

    1. upload a document  -> PENDING ingestion job
    2. poll the job        -> INDEXED (the worker does the work)
    3. list documents      -> registry shows the indexed document
    4. search              -> Knowledge Service retrieves it (real embeddings)

Requires the stack: postgres+pgvector, MinIO, Ollama (nomic-embed-text),
backend API and the ingestion worker all running (see docker-compose.yml).
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
# The shared sample corpus (backend/sample_docs) is the single source of
# truth — this smoke test ingests the same annual-leave policy that
# ``scripts/seed_knowledge.py`` ships.
FAQ_MD = (
    Path(__file__).resolve().parent.parent / "backend" / "sample_docs" / "annual_leave_policy.md"
).read_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE, help="backend base URL")
    parser.add_argument("--timeout", type=int, default=120, help="max seconds to wait for INDEXED")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=30)

    # 1. Upload.
    resp = client.post(
        "/api/knowledge/documents/upload",
        data={"category": "POLICY"},
        files={"file": ("annual_leave_policy.md", FAQ_MD.encode(), "text/markdown")},
    )
    resp.raise_for_status()
    uploaded = resp.json()
    print(f"[1] upload -> {uploaded}")
    assert uploaded["status"] == "PENDING", uploaded
    job_id = uploaded["ingestion_job_id"]

    # 2. Poll until the worker indexes it (or FAILED).
    deadline = time.monotonic() + args.timeout
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/knowledge/jobs/{job_id}").json()
        if job["status"] in ("INDEXED", "FAILED"):
            break
        time.sleep(2)
    print(f"[2] job   -> {job}")
    assert job and job["status"] == "INDEXED", f"job not INDEXED: {job}"

    # 3. Document registry.
    listing = client.get("/api/knowledge/documents").json()
    print(f"[3] docs  -> {listing}")
    assert any(d["status"] == "INDEXED" for d in listing["documents"])

    # 4. Search through the Knowledge Service (real nomic embeddings).
    search = client.get("/api/knowledge/search", params={"q": "how many days of annual leave"}).json()
    print(f"[4] search: confidence={search['confidence']}, hits={len(search['chunks'])}")
    for chunk in search["chunks"][:3]:
        print(f"    - {chunk['document_title']} :: {chunk['section_title']}: {chunk['text'][:70]!r}")
    assert search["chunks"], "search returned no chunks"
    assert search["citations"], "search returned no citations"

    # 5. Same bytes again -> SKIPPED_DUPLICATE (checksum dedup).
    dup = client.post(
        "/api/knowledge/documents/upload",
        data={"category": "POLICY"},
        files={"file": ("copy.md", FAQ_MD.encode(), "text/markdown")},
    ).json()
    print(f"[5] dedup -> {dup}")
    assert dup["status"] == "SKIPPED_DUPLICATE", dup

    print("\nE2E ingestion OK: upload -> worker -> INDEXED -> hybrid search -> dedup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
