from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.capabilities.settings import SettingsService
from app.db.sync_session import SessionLocal, init_db
from app.domain.outbox import OutboxJob
from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy
from app.evaluation.scoring import score_resume
from app.integrations.email import EmailProvider
from app.integrations.email.smtp import SmtpEmailProvider
from app.integrations.object_store import SyncS3ObjectStore
from app.knowledge.resume_extraction import extract_text
from app.repositories.outbox import OutboxRepo
from app.repositories.settings import SettingRepo

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

POLL_INTERVAL_SECONDS = 2.0


async def process_job(db: Session, job: OutboxJob, object_store: SyncS3ObjectStore, email: EmailProvider) -> None:
    """Dispatch an outbox job to its handler based on job type."""
    if job.job_type == "EVALUATE_APPLICATION":
        await _evaluate_application(db, job, object_store)
    elif job.job_type in {
        "SEND_INTERVIEW_INVITATION",
        "SEND_APPLICATION_REJECTED",
        "SEND_APPLICATION_RECEIVED",
        "SEND_NEW_APPLICATION_ALERT",
        "SEND_APPLICATION_WITHDRAWN",
    }:
        _send_email(db, job, email)
    else:
        raise RuntimeError(f"Unknown job type: {job.job_type}")


async def _evaluate_application(db: Session, job: OutboxJob, object_store: SyncS3ObjectStore) -> None:
    """Extract resume text, score it against the vacancy, and persist an evaluation row."""
    application_id = uuid.UUID(str(job.payload["application_id"]))
    object_key = str(job.payload["cv_object_key"])

    data, content_type = object_store.get_object(object_key)

    extraction = extract_text(data, object_key, content_type)
    application = db.get(Application, application_id)
    if application is None:
        raise RuntimeError("Application row not found.")

    if not extraction.text.strip():
        # no readable text — record a note as the evaluation, don't fail the app
        db.add(
            ApplicationEvaluation(
                application_id=application_id,
                score=0,
                overview=(
                    "No readable text could be extracted from the uploaded resume. "
                    "It may be a scanned image or in an unsupported format."
                ),
                raw_payload={"error": extraction.warning},
                model="none",
                prompt_version="none",
                evaluated_at=datetime.now(UTC),
            )
        )
        db.commit()
        return

    vacancy = db.get(Vacancy, application.vacancy_id)

    system_prompt = SettingRepo(db).get_value("resume_review_system_prompt")
    llm_overrides = SettingsService(db).resolved_llm_overrides()

    started = time.monotonic()
    result = await score_resume(
        resume_text=extraction.text,
        job_title=vacancy.title if vacancy else "",
        job_description=vacancy.description or "" if vacancy else "",
        system_prompt=system_prompt,
        api_base=llm_overrides["api_base"],
        model=llm_overrides["model"],
        api_key=llm_overrides["api_key"],
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    db.add(
        ApplicationEvaluation(
            application_id=application_id,
            score=result.score,
            overview=result.overview,
            raw_payload=result.raw_payload,
            model=result.model,
            prompt_version=result.prompt_version,
            latency_ms=latency_ms,
            evaluated_at=datetime.now(UTC),
        )
    )
    db.commit()


def _send_email(db: Session, job: OutboxJob, email: EmailProvider) -> None:
    """Send a notification email encoded in the job payload, raising if there is no recipient."""
    payload = job.payload
    to_email = str(payload["to_email"])
    subject = str(payload["subject"])
    body = str(payload["body"])
    if not to_email:
        raise RuntimeError("Email job has no recipient.")
    email.send(to_email=to_email, subject=subject, body=body)


async def worker_loop() -> None:
    """Poll the outbox continuously, claiming and processing one job at a time."""
    init_db()
    object_store = SyncS3ObjectStore()
    object_store.ensure_bucket()
    email: EmailProvider = SmtpEmailProvider()

    log.info("Worker started: polling outbox_job every %ss", POLL_INTERVAL_SECONDS)
    while True:
        db = SessionLocal()
        try:
            repo = OutboxRepo(db)
            job = repo.claim_next()
            db.commit()  # release the row lock (SELECT ... FOR UPDATE) once claimed
            if job is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            try:
                await process_job(db, job, object_store, email)
                repo.mark_succeeded(job)
                db.commit()
                log.info("Job %s %s succeeded", job.job_id, job.job_type)
            except Exception as err:  # noqa: BLE001
                db.rollback()
                job = db.get(OutboxJob, job.job_id)
                repo.mark_failed(job, str(err))
                db.commit()
                log.error("Job %s %s failed: %s", job.job_id, job.job_type, err)
        finally:
            db.close()


if __name__ == "__main__":
    asyncio.run(worker_loop())
