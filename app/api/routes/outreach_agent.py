"""
Outreach Agent endpoints.

POST /api/v1/outreach/accounts              Add sender email account
GET  /api/v1/outreach/accounts              List sender accounts
DELETE /api/v1/outreach/accounts/{id}       Remove sender account

POST /api/v1/outreach/jobs/start            Start outreach job (continuous)
DELETE /api/v1/outreach/jobs/stop           Stop outreach job
GET  /api/v1/outreach/jobs/status           Job status + today's stats

POST /api/v1/outreach/run-now               Run one cycle immediately (manual trigger)

GET  /api/v1/outreach/sent                  Sent email log for current user
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.api.dependencies import get_current_user
from app.storage.models import UserRecord, SenderEmailAccountRecord, OutreachSentRecord
from app.storage.database import AsyncSessionLocal
from app.utils.encryption import encrypt
from app.modules.outreach.agent import run_outreach_job
from app.core.logging import get_logger
from sqlmodel import select

router = APIRouter(prefix="/outreach", tags=["outreach-agent"])
logger = get_logger(__name__)

# In-memory job registry
_active_jobs: dict[int, bool] = {}   # user_id → running


# ── Sender account management ─────────────────────────────────────────────────

class AddAccountRequest(BaseModel):
    email_address: EmailStr
    display_name: str = ""
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str          # stored encrypted
    use_tls: bool = True
    daily_limit: int = 50


@router.post("/accounts", status_code=201)
async def add_sender_account(
    body: AddAccountRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Add an SMTP sender account. Password is encrypted before storage."""
    async with AsyncSessionLocal() as session:
        session.add(SenderEmailAccountRecord(
            user_id=current_user.id,
            email_address=str(body.email_address),
            display_name=body.display_name,
            smtp_host=body.smtp_host,
            smtp_port=body.smtp_port,
            smtp_username=body.smtp_username,
            smtp_password_encrypted=encrypt(body.smtp_password),
            use_tls=body.use_tls,
            daily_limit=body.daily_limit,
        ))
        await session.commit()
    logger.info("outreach.account_added", user_id=current_user.id, email=body.email_address)
    return {"status": "added", "email": str(body.email_address)}


@router.get("/accounts")
async def list_sender_accounts(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == current_user.id)
        )
        accounts = result.scalars().all()
    return {
        "accounts": [
            {
                "id": a.id,
                "email_address": a.email_address,
                "display_name": a.display_name,
                "smtp_host": a.smtp_host,
                "smtp_port": a.smtp_port,
                "daily_limit": a.daily_limit,
                "is_active": a.is_active,
            }
            for a in accounts
        ]
    }


@router.delete("/accounts/{account_id}")
async def remove_sender_account(
    account_id: int,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        acc = await session.get(SenderEmailAccountRecord, account_id)
        if not acc or acc.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Account not found")
        acc.is_active = False
        session.add(acc)
        await session.commit()
    return {"status": "deactivated"}


# ── Job management ────────────────────────────────────────────────────────────

async def _continuous_outreach(user_id: int, interval_minutes: int) -> None:
    """Runs outreach cycles on a schedule until stopped."""
    logger.info("outreach_job.started", user_id=user_id, interval_minutes=interval_minutes)
    while _active_jobs.get(user_id, False):
        result = await run_outreach_job(user_id)
        logger.info("outreach_job.cycle", user_id=user_id, **result)

        # Sleep in 10s chunks for responsive cancellation
        for _ in range(interval_minutes * 6):
            if not _active_jobs.get(user_id, False):
                break
            await asyncio.sleep(10)

    logger.info("outreach_job.stopped", user_id=user_id)
    _active_jobs.pop(user_id, None)


class StartJobRequest(BaseModel):
    interval_minutes: int = 60


@router.post("/jobs/start")
async def start_outreach_job(
    body: StartJobRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Start a continuous outreach job. Runs until stopped."""
    if _active_jobs.get(current_user.id):
        return {"status": "already_running", "user_id": current_user.id}
    _active_jobs[current_user.id] = True
    background_tasks.add_task(_continuous_outreach, current_user.id, body.interval_minutes)
    return {
        "status": "started",
        "user_id": current_user.id,
        "interval_minutes": body.interval_minutes,
        "message": "Outreach job started. Stop via DELETE /api/v1/outreach/jobs/stop",
    }


@router.delete("/jobs/stop")
async def stop_outreach_job(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    if not _active_jobs.get(current_user.id):
        raise HTTPException(status_code=404, detail="No active outreach job")
    _active_jobs[current_user.id] = False
    return {"status": "stopping", "message": "Current cycle will complete then stop."}


@router.get("/jobs/status")
async def get_job_status(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    from app.modules.outreach.agent import _get_sent_today
    from app.storage.models import SenderEmailAccountRecord
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == current_user.id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        sender = result.scalar_one_or_none()

    sent_today = 0
    if sender:
        sent_today = await _get_sent_today(current_user.id, sender.email_address)

    return {
        "is_running": _active_jobs.get(current_user.id, False),
        "sent_today": sent_today,
        "sender_email": sender.email_address if sender else None,
        "daily_limit": sender.daily_limit if sender else None,
    }


@router.post("/run-now")
async def run_now(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Trigger one outreach cycle immediately (manual)."""
    result = await run_outreach_job(current_user.id)
    return {"status": "completed", **result}


# ── Sent log ──────────────────────────────────────────────────────────────────

@router.get("/sent")
async def get_sent_log(
    current_user: UserRecord = Depends(get_current_user),
    limit: int = 100,
) -> dict:
    """Get the sent email log for the current user."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == current_user.id)
            .order_by(OutreachSentRecord.sent_at.desc())
            .limit(limit)
        )
        records = result.scalars().all()

    return {
        "total": len(records),
        "sent": [
            {
                "lead_id": r.lead_id,
                "sender_email": r.sender_email,
                "receiver_email": r.receiver_email,
                "subject": r.subject,
                "status": r.status,
                "sent_at": r.sent_at.isoformat(),
                "error": r.error_message,
            }
            for r in records
        ],
    }
