#!/usr/bin/env python3
"""Seed the knowledge base with the sample HR policy corpus.

Uploads every ``backend/sample_docs/*.md`` document to the running backend
and waits for each ingestion job to reach ``INDEXED``. Idempotent: the
orchestrator's SHA-256 checksum dedup reports ``SKIPPED_DUPLICATE`` for bytes
that are already indexed, so re-running is a no-op for what is already there.

The corpus is the single source of truth for the chat demo's knowledge
answers — leave-policy questions route to the knowledge agent (see
``agents/supervisor/route_intent.py``), which can only answer them if these
documents are indexed.

Requires the stack running (backend API + ingestion worker + MinIO + Ollama
embeddings); see ``make seed-knowledge``.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
SAMPLE_DOCS = Path(__file__).resolve().parent.parent / "backend" / "sample_docs"


def _upload_and_wait(client: httpx.Client, path: Path, *, timeout: int) -> dict:
    """Upload one document and poll its job until terminal, or raise."""
    resp = client.post(
        "/api/knowledge/documents/upload",
        data={"category": "POLICY"},
        files={"file": (path.name, path.read_bytes(), "text/markdown")},
    )
    resp.raise_for_status()
    uploaded = resp.json()
    if uploaded["status"] == "SKIPPED_DUPLICATE":
        return {"file": path.name, "status": "SKIPPED_DUPLICATE", "detail": uploaded}

    job_id = uploaded["ingestion_job_id"]
    deadline = time.monotonic() + timeout
    job = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/knowledge/jobs/{job_id}").json()
        if job["status"] in ("INDEXED", "FAILED"):
            break
        time.sleep(2)
    if job is None or job["status"] != "INDEXED":
        raise RuntimeError(f"{path.name}: job not INDEXED: {job}")
    return {"file": path.name, "status": "INDEXED", "detail": uploaded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE, help="backend base URL")
    parser.add_argument("--timeout", type=int, default=120, help="max seconds to wait per job")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    paths = sorted(SAMPLE_DOCS.glob("*.md"))
    if not paths:
        print(f"No sample documents found in {SAMPLE_DOCS}", file=sys.stderr)
        return 1

    print(f"Seeding {len(paths)} sample documents against {base} ...")
    client = httpx.Client(base_url=base, timeout=30)
    results: list[dict] = []
    failed = 0
    try:
        for path in paths:
            try:
                results.append(_upload_and_wait(client, path, timeout=args.timeout))
                print(f"  [ok] {path.name}")
            except Exception as exc:  # noqa: BLE001 - report every doc, keep going
                failed += 1
                results.append({"file": path.name, "status": "FAILED", "detail": str(exc)})
                print(f"  [!!] {path.name}: {exc}")
    finally:
        client.close()

    indexed = sum(1 for r in results if r["status"] == "INDEXED")
    skipped = sum(1 for r in results if r["status"] == "SKIPPED_DUPLICATE")
    print(f"\nKnowledge seed: {indexed} indexed, {skipped} already present (skipped), {failed} failed.")
    if failed:
        print("Re-run after fixing the reported documents; successful ones are deduped.", file=sys.stderr)
        return 1
    print("Sample KB ready — try: what is the annual leave policy?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
