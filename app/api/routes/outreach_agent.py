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
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.api.dependencies import get_current_user
from app.storage.models import (
    UserRecord,
    SenderEmailAccountRecord,
    OutreachSentRecord,
    OutreachReplyRecord,
    LeadLifecycleRecord,
    PipelineRunRecord,
)
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
    imap_host: Optional[str] = None
    imap_port: int = 993
    imap_username: Optional[str] = None
    imap_password: Optional[str] = None
    imap_use_ssl: bool = True


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
            imap_host=body.imap_host,
            imap_port=body.imap_port,
            imap_username=body.imap_username,
            imap_password_encrypted=encrypt(body.imap_password) if body.imap_password else None,
            imap_use_ssl=body.imap_use_ssl,
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


class SendByIndustryRequest(BaseModel):
    run_id: str
    industry: str   # e.g. "manufacturing" — matches category/industry field on leads


@router.post("/send-by-industry")
async def send_by_industry(
    body: SendByIndustryRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Send outreach emails to all APPROVED finalized leads in a specific industry
    within a given pipeline run.

    This is the per-industry outreach button on the Run Detail page.
    Only sends to leads that:
      - Have an approved finalized draft
      - Have a receiver_email set
      - Have not been sent to before (dedup)
      - Are in the specified industry/category
    """
    from app.modules.outreach.agent import (
        _already_sent, _send_email_async, _log_sent, _mark_contacted,
        _get_sent_today, _in_send_window,
    )
    from app.utils.encryption import decrypt
    from app.storage.models import SenderEmailAccountRecord, EnrichedLeadRecord

    # Load active sender
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == current_user.id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        sender = result.scalar_one_or_none()

    if not sender:
        raise HTTPException(status_code=400, detail="No active sender email account. Add one in Settings.")

    # Load approved drafts for this run
    async with AsyncSessionLocal() as session:
        from app.storage.models import FinalizedDraftRecord
        drafts_result = await session.execute(
            select(FinalizedDraftRecord)
            .where(FinalizedDraftRecord.pipeline_run_id == body.run_id)
            .where(FinalizedDraftRecord.approval_status == "APPROVED")
        )
        all_drafts = list(drafts_result.scalars().all())

        # Load enriched leads to filter by industry/category
        lead_ids = [d.lead_id for d in all_drafts]
        if not lead_ids:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "no_approved_drafts"}

        enr_result = await session.execute(
            select(EnrichedLeadRecord).where(EnrichedLeadRecord.lead_id.in_(lead_ids))
        )
        enriched_map = {e.lead_id: e for e in enr_result.scalars().all()}

    # Filter to the requested industry
    industry_lower = body.industry.lower()
    industry_drafts = [
        d for d in all_drafts
        if _matches_industry(enriched_map.get(d.lead_id), industry_lower)
    ]

    if not industry_drafts:
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": f"no_approved_drafts_for_industry_{body.industry}"}

    smtp_password = decrypt(sender.smtp_password_encrypted)
    sent = skipped = failed = 0

    for draft in industry_drafts:
        if not draft.receiver_email:
            skipped += 1
            continue

        if await _already_sent(current_user.id, draft.lead_id, draft.receiver_email):
            skipped += 1
            continue

        try:
            await _send_email_async(
                smtp_host=sender.smtp_host,
                smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username,
                smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=draft.receiver_email,
                subject=draft.final_subject,
                body=draft.final_body,
            )
            await _log_sent(current_user.id, draft.lead_id, sender.email_address,
                           draft.receiver_email, draft.final_subject)
            await _mark_contacted(draft.lead_id, current_user.id)
            sent += 1
            logger.info("outreach.industry_sent", lead_id=draft.lead_id,
                       industry=body.industry, to=draft.receiver_email)
        except Exception as e:
            await _log_sent(current_user.id, draft.lead_id, sender.email_address,
                           draft.receiver_email, draft.final_subject,
                           status="failed", error=str(e)[:500])
            failed += 1
            logger.error("outreach.industry_send_failed", lead_id=draft.lead_id, error=str(e)[:200])

    return {
        "industry": body.industry,
        "run_id": body.run_id,
        "total_eligible": len(industry_drafts),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


def _matches_industry(enriched, industry_lower: str) -> bool:
    """Check if an enriched lead matches the requested industry."""
    if enriched is None:
        return False
    fields = [
        (enriched.industry or "").lower(),
        (enriched.business_type or "").lower(),
    ]
    return any(industry_lower in f or f in industry_lower for f in fields if f)


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
                "campaign_stage": r.campaign_stage,
                "sent_at": r.sent_at.isoformat(),
                "error": r.error_message,
            }
            for r in records
        ],
    }


@router.get("/metrics")
async def get_engagement_metrics(
    current_user: UserRecord = Depends(get_current_user),
    days: int = 30,
) -> dict:
    """
    Engagement KPIs for outreach quality/performance.
    Includes reply intent mix, stage-level send performance, and lost reasons.
    """
    days = max(1, min(days, 365))
    since = datetime.utcnow() - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        sent_result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == current_user.id)
            .where(OutreachSentRecord.sent_at >= since)
            .order_by(OutreachSentRecord.sent_at.desc())
        )
        sent_rows = list(sent_result.scalars().all())

        reply_result = await session.execute(
            select(OutreachReplyRecord)
            .where(OutreachReplyRecord.user_id == current_user.id)
            .where(OutreachReplyRecord.received_at >= since)
            .order_by(OutreachReplyRecord.received_at.desc())
        )
        reply_rows = list(reply_result.scalars().all())

        run_result = await session.execute(
            select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == current_user.id)
        )
        run_ids = [r[0] for r in run_result.all()]
        lifecycle_result = await session.execute(
            select(LeadLifecycleRecord)
            .where(LeadLifecycleRecord.pipeline_run_id.in_(run_ids))
        ) if run_ids else None
        lifecycle_rows = list(lifecycle_result.scalars().all()) if lifecycle_result is not None else []

    sent_success = [r for r in sent_rows if r.status == "sent"]
    sent_failed = [r for r in sent_rows if r.status != "sent"]

    stage_counts: dict[str, dict] = {
        "initial": {"sent": 0, "failed": 0},
        "followup": {"sent": 0, "failed": 0},
        "reply": {"sent": 0, "failed": 0},
    }
    for row in sent_rows:
        stage = row.campaign_stage if row.campaign_stage in stage_counts else "initial"
        if row.status == "sent":
            stage_counts[stage]["sent"] += 1
        else:
            stage_counts[stage]["failed"] += 1

    intent_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for reply in reply_rows:
        if reply.intent in intent_counts:
            intent_counts[reply.intent] += 1

    total_replies = len(reply_rows)
    reply_rate = (total_replies / len(sent_success)) if sent_success else 0.0
    positive_rate = (intent_counts["positive"] / total_replies) if total_replies else 0.0
    negative_rate = (intent_counts["negative"] / total_replies) if total_replies else 0.0

    lost_rows = [r for r in lifecycle_rows if r.current_status == "LOST" and r.notes]
    lost_reason_counts: dict[str, int] = {}
    for row in lost_rows:
        reason = (row.notes or "unspecified").strip()[:120]
        lost_reason_counts[reason] = lost_reason_counts.get(reason, 0) + 1

    return {
        "window_days": days,
        "as_of_utc": datetime.utcnow().isoformat(),
        "volume": {
            "total_attempts": len(sent_rows),
            "total_sent": len(sent_success),
            "total_failed": len(sent_failed),
            "total_replies": total_replies,
        },
        "rates": {
            "delivery_success_rate": (len(sent_success) / len(sent_rows)) if sent_rows else 0.0,
            "reply_rate": reply_rate,
            "positive_reply_rate": positive_rate,
            "negative_reply_rate": negative_rate,
        },
        "by_stage": stage_counts,
        "reply_intents": intent_counts,
        "lost_reasons": lost_reason_counts,
    }
