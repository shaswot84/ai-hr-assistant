from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.repositories.audit import AuditRepo

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogItemOut(BaseModel):
    """Enriched audit log entry."""

    audit_id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    actor_role: str | None = None
    action: str
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    authorization_result: str = "ALLOW"
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    request_id: uuid.UUID | None = None
    created_at: datetime


class AuditLogsListOut(BaseModel):
    """Paginated list of audit logs with total counts."""

    items: list[AuditLogItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditFiltersOut(BaseModel):
    """Available filters and aggregate summary statistics."""

    actions: list[str]
    target_types: list[str]
    total_count: int
    today_count: int
    unique_actors_count: int


@router.get("/logs", response_model=AuditLogsListOut)
async def list_audit_logs(
    page: int = Query(1, ge=1, description="1-indexed page number"),
    page_size: int = Query(25, ge=1, le=200, description="Number of items per page"),
    action: str | None = Query(None, description="Filter by action name"),
    target_type: str | None = Query(None, description="Filter by target type"),
    actor_user_id: uuid.UUID | None = Query(None, description="Filter by actor user ID"),
    target_id: uuid.UUID | None = Query(None, description="Filter by target ID"),
    authorization_result: str | None = Query(None, description="Filter by authorization result"),
    search: str | None = Query(None, description="Free text search across action, target, actor"),
    start_date: datetime | None = Query(None, description="Earliest created_at timestamp (inclusive)"),
    end_date: datetime | None = Query(None, description="Latest created_at timestamp (inclusive)"),
    user: UserContext = Depends(require_role("HR_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """List audit log entries with multi-attribute filtering, search, and pagination."""
    repo = AuditRepo(db)
    offset = (page - 1) * page_size
    items, total = await repo.list_logs(
        action=action,
        target_type=target_type,
        actor_user_id=actor_user_id,
        target_id=target_id,
        authorization_result=authorization_result,
        search=search,
        start_date=start_date,
        end_date=end_date,
        limit=page_size,
        offset=offset,
    )

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return AuditLogsListOut(
        items=[
            AuditLogItemOut(
                audit_id=entry.audit_id,
                actor_user_id=entry.actor_user_id,
                actor_name=entry.actor_name,
                actor_email=entry.actor_email,
                actor_role=entry.actor_role,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                authorization_result=entry.authorization_result,
                previous_state=entry.previous_state,
                new_state=entry.new_state,
                request_id=entry.request_id,
                created_at=entry.created_at,
            )
            for entry in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/filters", response_model=AuditFiltersOut)
async def get_audit_filter_options(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Fetch distinct actions, target types, and aggregate stats for filter menus."""
    repo = AuditRepo(db)
    opts = await repo.get_filter_options()
    return AuditFiltersOut(
        actions=opts["actions"],
        target_types=opts["target_types"],
        total_count=opts["total_count"],
        today_count=opts["today_count"],
        unique_actors_count=opts["unique_actors_count"],
    )


@router.get("/logs/{audit_id}", response_model=AuditLogItemOut)
async def get_audit_log_detail(
    audit_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single enriched audit log entry by its UUID."""
    repo = AuditRepo(db)
    entry = await repo.get_by_id(audit_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log entry not found")

    return AuditLogItemOut(
        audit_id=entry.audit_id,
        actor_user_id=entry.actor_user_id,
        actor_name=entry.actor_name,
        actor_email=entry.actor_email,
        actor_role=entry.actor_role,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        authorization_result=entry.authorization_result,
        previous_state=entry.previous_state,
        new_state=entry.new_state,
        request_id=entry.request_id,
        created_at=entry.created_at,
    )

