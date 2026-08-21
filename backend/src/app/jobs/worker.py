from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.settings import SettingsService
from app.db.session import async_session_factory, init_db
from app.domain.outbox import OutboxJob
from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy
from app.evaluation.resume_structuring import extract_structured_resume
from app.evaluation.scoring import score_resume
from app.integrations.email import EmailProvider
from app.integrations.email.smtp import SmtpEmailProvider
from app.integrations.object_store import SyncS3ObjectStore
from app.knowledge.resume_extraction import extract_text
from app.model_gateway.provider import ChatProviderError
from app.repositories.outbox import OutboxRepo

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

POLL_INTERVAL_SECONDS = 2.0


async def process_job(
    db: AsyncSession, job: OutboxJob, object_store: SyncS3ObjectStore, email: EmailProvider
) -> None:
    """Dispatch an outbox job to its handler based on job type."""
    if job.job_type == "EVALUATE_APPLICATION":
        await _evaluate_application(db, job, object_store)
    elif job.job_type in {
        "SEND_INTERVIEW_INVITATION",
        "SEND_APPLICATION_REJECTED",
        "SEND_APPLICATION_RECEIVED",
        "SEND_NEW_APPLICATION_ALERT",
        "SEND_APPLICATION_WITHDRAWN",
        "SEND_LEAVE_REQUEST_RECEIVED",
        "SEND_NEW_LEAVE_REQUEST_ALERT",
        "SEND_LEAVE_APPROVAL_EMAIL",
        "SEND_LEAVE_REJECTED",
    }:
        _send_email(db, job, email)
    else:
        raise RuntimeError(f"Unknown job type: {job.job_type}")


async def _evaluate_application(
    db: AsyncSession, job: OutboxJob, object_store: SyncS3ObjectStore
) -> None:
    """Extract resume text, score it against the vacancy, and persist an evaluation row."""
    application_id = uuid.UUID(str(job.payload["application_id"]))
    object_key = str(job.payload["cv_object_key"])

    data, content_type = object_store.get_object(object_key)

    extraction = extract_text(data, object_key, content_type)
    application = await db.get(Application, application_id)
    if application is None:
        raise RuntimeError("Application row not found.")

    if not extraction.text.strip():
        # no readable text — record a note as the evaluation, don't fail the app
        db.add(
            ApplicationEvaluation(
                application_id=application_id,
                overview=(
                    "No readable text could be extracted from the uploaded resume. "
                    "It may be a scanned image or in an unsupported format."
                ),
                raw_payload={"error": extraction.warning},
                failed=True,
                model="none",
                prompt_version="none",
                evaluated_at=datetime.now(UTC),
            )
        )
        await db.commit()
        return

    vacancy = await db.get(Vacancy, application.vacancy_id)

    settings_svc = SettingsService()
    system_prompt = settings_svc.resolved_prompt()
    user_prompt = settings_svc.resolved_resume_review_user_prompt()
    structuring_system_prompt = settings_svc.resolved_structuring_system_prompt()
    structuring_user_prompt = settings_svc.resolved_structuring_user_prompt()
    llm_overrides = settings_svc.resolved_llm_overrides()

    started = time.monotonic()
    try:
        structured = await extract_structured_resume(
            extraction.text,
            system_prompt=structuring_system_prompt,
            user_prompt=structuring_user_prompt,
            api_base=llm_overrides["api_base"],
            model=llm_overrides["model"],
            api_key=llm_overrides["api_key"],
        )
        result = await score_resume(
            resume_text=extraction.text,
            job_title=vacancy.title if vacancy else "",
            job_description=vacancy.description or "" if vacancy else "",
            structured=structured,
            scoring_keywords=vacancy.scoring_keywords if vacancy else None,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_base=llm_overrides["api_base"],
            model=llm_overrides["model"],
            api_key=llm_overrides["api_key"],
        )
    except ChatProviderError as err:
        db.add(
            ApplicationEvaluation(
                application_id=application_id,
                overview=str(err),
                raw_payload={"error": str(err)},
                failed=True,
                model="none",
                prompt_version="none",
                evaluated_at=datetime.now(UTC),
            )
        )
        await db.commit()
        return
    latency_ms = int((time.monotonic() - started) * 1000)

    raw_payload = {**result.raw_payload, "structuredResume": structured.to_dict()}
    db.add(
        ApplicationEvaluation(
            application_id=application_id,
            overview=result.overview,
            raw_payload=raw_payload,
            keyword_score=result.keyword_score,
            model=result.model,
            prompt_version=result.prompt_version,
            latency_ms=latency_ms,
            evaluated_at=datetime.now(UTC),
        )
    )
    await db.commit()


def _send_email(db: AsyncSession, job: OutboxJob, email: EmailProvider) -> None:
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
    await init_db()
    object_store = SyncS3ObjectStore()
    object_store.ensure_bucket()
    email: EmailProvider = SmtpEmailProvider()

    log.info("Worker started: polling outbox_job every %ss", POLL_INTERVAL_SECONDS)
    while True:
        async with async_session_factory() as db:
            try:
                repo = OutboxRepo(db)
                job = await repo.claim_next()
                await db.commit()  # release the row lock once claimed
                if job is None:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                try:
                    await process_job(db, job, object_store, email)
                    await repo.mark_succeeded(job)
                    await db.commit()
                    log.info("Job %s %s succeeded", job.job_id, job.job_type)
                except Exception as err:  # noqa: BLE001
                    await db.rollback()
                    job = await db.get(OutboxJob, job.job_id)
                    await repo.mark_failed(job, str(err))
                    await db.commit()
                    log.error("Job %s %s failed: %s", job.job_id, job.job_type, err)
            except Exception as err:
                log.error("Error in worker loop: %s", err)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(worker_loop())

