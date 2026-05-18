"""
Outreach Agent endpoints.

GET   /api/v1/outreach/account              Current user's persisted sender SMTP/IMAP (no secrets)
PUT   /api/v1/outreach/account             Upsert that sender identity (until changed/disconnected)

POST /api/v1/outreach/accounts             Legacy save — same upsert as PUT (does not multiply rows)
GET  /api/v1/outreach/accounts             List sender account rows for this user
DELETE /api/v1/outreach/accounts/{id}      Deactivate sender account row

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
from sqlalchemy import delete
from typing import Optional

from app.api.dependencies import get_current_user
from app.core.config import settings as app_settings
from app.storage.models import (
    UserRecord,
    SenderEmailAccountRecord,
    OutreachSentRecord,
    OutreachReplyRecord,
    LeadLifecycleRecord,
    PipelineRunRecord,
    OutreachRecord,
    EnrichedLeadRecord,
    FinalizedDraftRecord,
    MeetingHandoffRecord,
    SandboxTestInboxRecord,
    SandboxLeadRecipientMapRecord,
)
from app.storage.database import AsyncSessionLocal
from app.utils.encryption import encrypt
from app.modules.outreach.agent import run_outreach_job
from app.modules.outreach.email_sanitize import clean_outreach_copy
from app.core.logging import get_logger
from app.services.sandbox_outreach import (
    SandboxConfigError,
    resolve_smtp_receiver,
    is_sandbox_pipeline_run,
)
from sqlmodel import select

router = APIRouter(prefix="/outreach", tags=["outreach-agent"])
logger = get_logger(__name__)

# In-memory job registry
_active_jobs: dict[str, bool] = {}   # user_id → running


def _require_sandbox_api() -> None:
    if not app_settings.sandbox_outreach_enabled:
        raise HTTPException(status_code=404, detail="Not found")


# ── Sender account management ─────────────────────────────────────────────────

class PersistSenderAccountRequest(BaseModel):
    """Create or replace the user's primary sender identity. Omit blank passwords when updating to keep stored secrets."""
    email_address: EmailStr
    display_name: str = ""
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: Optional[str] = None       # empty / omitted on update keeps existing ciphertext
    use_tls: bool = True
    daily_limit: int = 50
    imap_host: Optional[str] = None
    imap_port: int = 993
    imap_username: Optional[str] = None
    imap_password: Optional[str] = None       # empty / omitted on update keeps existing
    imap_use_ssl: bool = True


# Backwards-compat alias
AddAccountRequest = PersistSenderAccountRequest


async def _upsert_resolve_sender_row(
    session, user_id: str,
) -> tuple[SenderEmailAccountRecord | None, bool]:
    """
    Target row for create/update persisted sender.
    Prefer the active row; if everything is deactivated, reuse the newest row so Save re-enables it.
    Returns (record_or_none, needs_fresh_insert).
    """
    result = await session.execute(
        select(SenderEmailAccountRecord)
        .where(SenderEmailAccountRecord.user_id == user_id)
        .order_by(SenderEmailAccountRecord.id.desc())
    )
    rows = list(result.scalars().all())
    if not rows:
        return None, True
    preferred = next((r for r in rows if r.is_active), rows[0])
    return preferred, False


async def _get_active_sender_row(session, user_id: str) -> SenderEmailAccountRecord | None:
    """Only rows marked active drive sending + Settings read view."""
    r = await session.execute(
        select(SenderEmailAccountRecord)
        .where(SenderEmailAccountRecord.user_id == user_id)
        .where(SenderEmailAccountRecord.is_active == True)
        .order_by(SenderEmailAccountRecord.id.desc())
        .limit(1),
    )
    return r.scalar_one_or_none()


def _serialize_sender_public(acc: SenderEmailAccountRecord, *, configured: bool = True) -> dict:
    return {
        "configured": configured,
        "id": acc.id,
        "email_address": acc.email_address,
        "display_name": acc.display_name,
        "smtp_host": acc.smtp_host,
        "smtp_port": acc.smtp_port,
        "smtp_username": acc.smtp_username,
        "smtp_password_configured": bool(acc.smtp_password_encrypted),
        "use_tls": acc.use_tls,
        "daily_limit": acc.daily_limit,
        "imap_host": acc.imap_host,
        "imap_port": acc.imap_port,
        "imap_username": acc.imap_username,
        "imap_password_configured": bool(acc.imap_password_encrypted),
        "imap_use_ssl": acc.imap_use_ssl,
        "is_active": acc.is_active,
    }


async def persist_user_sender_account(
    user_id: str,
    body: PersistSenderAccountRequest,
) -> tuple[SenderEmailAccountRecord, str]:
    """Upsert exactly one logical sender configuration per user. Returns (record, action)."""
    async with AsyncSessionLocal() as session:
        row, is_new = await _upsert_resolve_sender_row(session, user_id)

        if is_new:
            pw = (body.smtp_password or "").strip()
            if not pw:
                raise HTTPException(
                    status_code=400,
                    detail="SMTP password is required when saving a sender account for the first time.",
                )
            imap_pw = body.imap_password.strip() if body.imap_password else ""
            session.add(SenderEmailAccountRecord(
                user_id=user_id,
                email_address=str(body.email_address),
                display_name=body.display_name,
                smtp_host=body.smtp_host,
                smtp_port=body.smtp_port,
                smtp_username=body.smtp_username,
                smtp_password_encrypted=encrypt(pw),
                use_tls=body.use_tls,
                daily_limit=body.daily_limit,
                imap_host=body.imap_host.strip() if body.imap_host else None,
                imap_port=body.imap_port,
                imap_username=body.imap_username.strip() if body.imap_username else None,
                imap_password_encrypted=encrypt(imap_pw) if imap_pw else None,
                imap_use_ssl=body.imap_use_ssl,
                is_active=True,
            ))
            await session.commit()
            new_row = (
                await session.execute(
                    select(SenderEmailAccountRecord)
                    .where(SenderEmailAccountRecord.user_id == user_id)
                    .order_by(SenderEmailAccountRecord.id.desc())
                    .limit(1)
                )
            ).scalar_one()
            logger.info("outreach.account_created", user_id=user_id, email=body.email_address)
            return new_row, "created"

        row.email_address = str(body.email_address)
        row.display_name = body.display_name
        row.smtp_host = body.smtp_host
        row.smtp_port = body.smtp_port
        row.smtp_username = body.smtp_username
        if (body.smtp_password or "").strip():
            row.smtp_password_encrypted = encrypt(body.smtp_password.strip())
        row.use_tls = body.use_tls
        row.daily_limit = body.daily_limit
        row.imap_host = body.imap_host.strip() if body.imap_host else None
        row.imap_port = body.imap_port
        row.imap_username = body.imap_username.strip() if body.imap_username else None

        ip = body.imap_password
        if ip is not None:
            ip_stripped = ip.strip()
            if ip_stripped:
                row.imap_password_encrypted = encrypt(ip_stripped)
            else:
                row.imap_password_encrypted = None

        row.imap_use_ssl = body.imap_use_ssl
        row.is_active = True

        siblings = (
            await session.execute(
                select(SenderEmailAccountRecord).where(SenderEmailAccountRecord.user_id == user_id)
            )
        ).scalars().all()
        for s in siblings:
            if row.id is not None and s.id != row.id:
                s.is_active = False
                session.add(s)

        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.info("outreach.account_updated", user_id=user_id, email=body.email_address, id=row.id)
        return row, "updated"


@router.get("/account")
async def get_sender_account_primary(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Return the persisted sender SMTP/IMAP identity for this user (no secret values).
    Used by Settings UI for read/edit flows.
    """
    async with AsyncSessionLocal() as session:
        active = await _get_active_sender_row(session, current_user.id)
        if active is None:
            return {"configured": False}

    return _serialize_sender_public(active)


@router.put("/account")
async def put_sender_account_primary(
    body: PersistSenderAccountRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Create or update the user's primary outbound sender credentials (persisted until changed)."""
    rec, action = await persist_user_sender_account(current_user.id, body)
    public = _serialize_sender_public(rec)
    public.update({"status": action})
    return public


@router.post("/accounts", status_code=201)
async def add_sender_account(
    body: PersistSenderAccountRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Backwards-compatible save endpoint: upserts the same single logical sender identity
    (does not accumulate duplicate accounts on each Save).
    """
    rec, action = await persist_user_sender_account(current_user.id, body)
    return {"status": action, "email": rec.email_address, "id": rec.id}


@router.get("/accounts")
async def list_sender_accounts(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == current_user.id)
            .order_by(SenderEmailAccountRecord.id.desc())
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
                "smtp_username": a.smtp_username,
                "use_tls": a.use_tls,
                "daily_limit": a.daily_limit,
                "imap_host": a.imap_host,
                "imap_port": a.imap_port,
                "imap_username": a.imap_username,
                "imap_use_ssl": a.imap_use_ssl,
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

async def _continuous_outreach(user_id: str, interval_minutes: int) -> None:
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


class SendLeadRequest(BaseModel):
    lead_id: str
    receiver_email: Optional[str] = None


@router.post("/send-lead")
async def send_single_lead_outreach(
    body: SendLeadRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Send outreach for a single lead, optionally overriding receiver email.
    Priority: explicit receiver_email -> finalized receiver_email -> enriched contact_email.
    """
    from app.modules.outreach.agent import _already_sent, _send_email_async, _log_sent, _mark_contacted
    from app.utils.encryption import decrypt
    from app.services.settings import get_settings

    async with AsyncSessionLocal() as session:
        sender_result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == current_user.id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        sender = sender_result.scalar_one_or_none()
        if not sender:
            raise HTTPException(status_code=400, detail="No active sender email account configured in settings.")

        run_result = await session.execute(
            select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == current_user.id)
        )
        run_ids = [r[0] for r in run_result.all()]
        if not run_ids:
            raise HTTPException(status_code=404, detail="No runs found for user.")

        draft_result = await session.execute(
            select(OutreachRecord)
            .where(OutreachRecord.lead_id == body.lead_id)
            .where(OutreachRecord.pipeline_run_id.in_(run_ids))
            .order_by(OutreachRecord.generated_at.desc())
            .limit(1)
        )
        draft = draft_result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status_code=404, detail=f"No generated outreach draft found for lead {body.lead_id}.")

        finalized = await session.get(FinalizedDraftRecord, body.lead_id)
        enriched = await session.get(EnrichedLeadRecord, body.lead_id)
        pipeline_run_for_lead = draft.pipeline_run_id

    natural_receiver = (
        (body.receiver_email or "").strip()
        or (finalized.receiver_email if finalized and finalized.receiver_email else "")
        or (enriched.contact_email if enriched and enriched.contact_email else "")
    )
    if not natural_receiver:
        raise HTTPException(status_code=400, detail="No receiver email available. Provide one or enrich contact details first.")

    sandbox = await is_sandbox_pipeline_run(current_user.id, pipeline_run_for_lead)
    try:
        smtp_receiver = await resolve_smtp_receiver(
            current_user.id,
            body.lead_id,
            natural_receiver,
            sandbox_pipeline=sandbox,
        )
    except SandboxConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if await _already_sent(current_user.id, body.lead_id, smtp_receiver):
        return {"status": "skipped", "reason": "already_sent", "lead_id": body.lead_id, "receiver_email": smtp_receiver}

    subject = draft.email_subject
    mail_body = draft.email_body
    subject, mail_body = clean_outreach_copy(subject, mail_body, for_send=True)

    smtp_password = decrypt(sender.smtp_password_encrypted)
    out_mid = await _send_email_async(
        smtp_host=sender.smtp_host,
        smtp_port=sender.smtp_port,
        smtp_username=sender.smtp_username,
        smtp_password=smtp_password,
        use_tls=sender.use_tls,
        from_email=sender.email_address,
        from_name=sender.display_name or sender.email_address,
        to_email=smtp_receiver,
        subject=subject,
        body=mail_body,
    )
    await _log_sent(
        current_user.id,
        body.lead_id,
        sender.email_address,
        smtp_receiver,
        subject,
        campaign_stage="initial",
        outbound_message_id=out_mid,
    )
    await _mark_contacted(body.lead_id, current_user.id)
    return {
        "status": "sent",
        "lead_id": body.lead_id,
        "receiver_email": natural_receiver,
        "smtp_envelope_to": smtp_receiver,
        "sandbox_routing": sandbox,
        "tone": (await get_settings(current_user.id)).ai_agent.email_tone,
    }


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

    sandbox_run = False
    # Load approved drafts for this run
    async with AsyncSessionLocal() as session:
        from app.storage.models import FinalizedDraftRecord
        run_own = await session.get(PipelineRunRecord, body.run_id)
        if not run_own or run_own.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Run not found.")
        sandbox_run = bool(getattr(run_own, "sandbox_outreach", False))

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
        natural_rec = (draft.receiver_email or "").strip()
        if not natural_rec:
            skipped += 1
            continue

        try:
            smtp_to = await resolve_smtp_receiver(
                current_user.id,
                draft.lead_id,
                natural_rec,
                sandbox_pipeline=sandbox_run,
            )
        except SandboxConfigError:
            skipped += 1
            continue

        if await _already_sent(current_user.id, draft.lead_id, smtp_to):
            skipped += 1
            continue

        subj, bdy = clean_outreach_copy(draft.final_subject, draft.final_body, for_send=True)
        try:
            out_mid_i = await _send_email_async(
                smtp_host=sender.smtp_host,
                smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username,
                smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=smtp_to,
                subject=subj,
                body=bdy,
            )
            await _log_sent(current_user.id, draft.lead_id, sender.email_address,
                           smtp_to, subj, outbound_message_id=out_mid_i)
            await _mark_contacted(draft.lead_id, current_user.id)
            sent += 1
            logger.info("outreach.industry_sent", lead_id=draft.lead_id,
                       industry=body.industry, to=smtp_to, sandbox=sandbox_run)
        except Exception as e:
            await _log_sent(current_user.id, draft.lead_id, sender.email_address,
                           smtp_to, subj,
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


# ── Sandbox test inboxes (SMTP redirect targets) ────────────────────────────


class SandboxInboxesReplaceRequest(BaseModel):
    """Replace this user's sandbox inbox list. Incoming addresses are normalized (lower/strip)."""

    emails: list[EmailStr]


@router.get("/sandbox/inboxes")
async def list_sandbox_inboxes(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    _require_sandbox_api()
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(SandboxTestInboxRecord)
            .where(SandboxTestInboxRecord.user_id == current_user.id)
            .order_by(SandboxTestInboxRecord.id.asc()),
        )
        rows = list(r.scalars().all())
    return {
        "inboxes": [{"id": x.id, "email": x.email, "is_active": x.is_active} for x in rows],
        "total": len(rows),
    }


@router.put("/sandbox/inboxes")
async def put_sandbox_inboxes(
    body: SandboxInboxesReplaceRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """
    Replace all sandbox inboxes for this user.
    Use during development / staging; hide this API in production via SANDBOX_OUTREACH_ENABLED=false.
    """
    _require_sandbox_api()
    uniq: list[str] = []
    seen: set[str] = set()
    for raw in body.emails:
        e = str(raw).strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        uniq.append(e)
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(SandboxTestInboxRecord).where(
                SandboxTestInboxRecord.user_id == current_user.id,
            )
        )
        for e in uniq:
            session.add(
                SandboxTestInboxRecord(
                    user_id=current_user.id,
                    email=e,
                    is_active=True,
                )
            )
        await session.commit()
    return {"status": "replaced", "count": len(uniq)}


@router.delete("/sandbox/inboxes/{inbox_id}")
async def delete_sandbox_inbox_row(
    inbox_id: int,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    _require_sandbox_api()
    async with AsyncSessionLocal() as session:
        row = await session.get(SandboxTestInboxRecord, inbox_id)
        if not row or row.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Inbox row not found")
        await session.delete(row)
        await session.commit()
    return {"status": "deleted"}


@router.delete("/sandbox/lead-recipient-map")
async def clear_sandbox_lead_recipient_map(
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Clear persisted lead→sandbox assignments (e.g. reset before a new sandbox campaign)."""
    _require_sandbox_api()
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(SandboxLeadRecipientMapRecord).where(
                SandboxLeadRecipientMapRecord.user_id == current_user.id,
            )
        )
        await session.commit()
    return {"status": "cleared"}


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


@router.get("/meeting-handoffs")
async def get_meeting_handoffs(
    current_user: UserRecord = Depends(get_current_user),
    status: Optional[str] = None,
    limit: int = 100,
) -> dict:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(MeetingHandoffRecord)
            .where(MeetingHandoffRecord.user_id == current_user.id)
            .order_by(MeetingHandoffRecord.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(MeetingHandoffRecord.status == status)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return {
        "total": len(rows),
        "handoffs": [
            {
                "id": r.id,
                "lead_id": r.lead_id,
                "receiver_email": r.receiver_email,
                "contact_name": r.contact_name,
                "contact_role": r.contact_role,
                "meeting_date": r.meeting_date,
                "meeting_time": r.meeting_time,
                "timezone": r.timezone,
                "notes": r.notes,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
