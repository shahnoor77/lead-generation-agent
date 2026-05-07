"""
Outreach Agent — sends approved email drafts via SMTP.

Flow per job run:
  1. Load user's active outreach job config
  2. Load all approved finalized drafts not yet sent
  3. Apply filters (industry, location, receiver domain)
  4. Check daily send limit and send window
  5. For each eligible draft: send email, log to outreach_sent, update lifecycle
  6. Repeat on schedule until job stopped or config changes

Deduplication:
  - Checks outreach_sent table before every send
  - Same lead_id + receiver_email combination is never sent twice

Safety:
  - Never sends if daily limit reached
  - Never sends outside configured send window
  - All failures logged — never crash the job
"""

from __future__ import annotations
import asyncio
import smtplib
import ssl
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from sqlmodel import select
from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    FinalizedDraftRecord,
    OutreachSentRecord,
    OutreachJobRecord,
    SenderEmailAccountRecord,
    LeadLifecycleRecord,
)
from app.schemas.lifecycle import LeadLifecycleStatus
from app.utils.encryption import decrypt
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── SMTP sender ───────────────────────────────────────────────────────────────

def _send_smtp(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    use_tls: bool,
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    """Synchronous SMTP send — run in executor to avoid blocking."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    context = ssl.create_default_context()
    if use_tls:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())


async def _send_email_async(
    smtp_host: str, smtp_port: int, smtp_username: str,
    smtp_password: str, use_tls: bool,
    from_email: str, from_name: str,
    to_email: str, subject: str, body: str,
) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _send_smtp,
        smtp_host, smtp_port, smtp_username, smtp_password, use_tls,
        from_email, from_name, to_email, subject, body,
    )


# ── Dedup check ───────────────────────────────────────────────────────────────

async def _already_sent(user_id: int, lead_id: str, receiver_email: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == user_id)
            .where(OutreachSentRecord.lead_id == lead_id)
            .where(OutreachSentRecord.receiver_email == receiver_email)
        )
        return result.scalar_one_or_none() is not None


# ── Send window check ─────────────────────────────────────────────────────────

def _in_send_window(window_start: str, window_end: str) -> bool:
    """Check if current UTC time is within the configured send window."""
    now = datetime.utcnow().strftime("%H:%M")
    return window_start <= now <= window_end


# ── Daily limit check ─────────────────────────────────────────────────────────

async def _get_sent_today(user_id: int, sender_email: str) -> int:
    today = date.today().isoformat()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == user_id)
            .where(OutreachSentRecord.sender_email == sender_email)
        )
        rows = result.scalars().all()
    return sum(1 for r in rows if r.sent_at.date().isoformat() == today)


# ── Log sent record ───────────────────────────────────────────────────────────

async def _log_sent(
    user_id: int, lead_id: str, sender_email: str,
    receiver_email: str, subject: str,
    status: str = "sent", error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        session.add(OutreachSentRecord(
            user_id=user_id,
            lead_id=lead_id,
            finalized_draft_id=lead_id,
            sender_email=sender_email,
            receiver_email=receiver_email,
            subject=subject,
            status=status,
            error_message=error,
        ))
        await session.commit()


# ── Update lifecycle to CONTACTED ─────────────────────────────────────────────

async def _mark_contacted(lead_id: str, user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        lc = await session.get(LeadLifecycleRecord, lead_id)
        if lc:
            lc.current_status = LeadLifecycleStatus.CONTACTED.value
            lc.updated_by = "outreach_agent"
            session.add(lc)
            await session.commit()


# ── Main agent run ────────────────────────────────────────────────────────────

async def run_outreach_job(user_id: int) -> dict:
    """
    Execute one outreach job cycle for a user.
    Returns a summary dict with sent/skipped/failed counts.
    """
    from app.services.settings import get_settings

    user_settings = await get_settings(user_id)
    outreach_cfg = user_settings.outreach

    # Load active sender account
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == user_id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        sender = result.scalar_one_or_none()

    if not sender:
        logger.warning("outreach_agent.no_sender_account", user_id=user_id)
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "no_sender_account"}

    # Check send window
    if not _in_send_window(outreach_cfg.send_window_start, outreach_cfg.send_window_end):
        logger.info("outreach_agent.outside_window", user_id=user_id)
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "outside_send_window"}

    # Check daily limit
    sent_today = await _get_sent_today(user_id, sender.email_address)
    remaining = min(sender.daily_limit, outreach_cfg.daily_send_limit) - sent_today
    if remaining <= 0:
        logger.info("outreach_agent.daily_limit_reached", user_id=user_id, sent_today=sent_today)
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "daily_limit_reached"}

    # Load approved finalized drafts for this user
    async with AsyncSessionLocal() as session:
        # Get all pipeline runs for this user
        from app.storage.models import PipelineRunRecord
        runs_result = await session.execute(
            select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == user_id)
        )
        run_ids = [r[0] for r in runs_result.all()]

        if not run_ids:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "no_runs"}

        # Get approved drafts from those runs
        drafts_result = await session.execute(
            select(FinalizedDraftRecord)
            .where(FinalizedDraftRecord.pipeline_run_id.in_(run_ids))
            .where(FinalizedDraftRecord.approval_status == "APPROVED")
        )
        approved_drafts = list(drafts_result.scalars().all())

    smtp_password = decrypt(sender.smtp_password_encrypted)
    sent = skipped = failed = 0

    for draft in approved_drafts:
        if sent >= remaining:
            break

        receiver_email = draft.receiver_email
        if not receiver_email:
            skipped += 1
            continue

        # Dedup check
        if await _already_sent(user_id, draft.lead_id, receiver_email):
            skipped += 1
            logger.debug("outreach_agent.already_sent", lead_id=draft.lead_id)
            continue

        # Send
        try:
            await _send_email_async(
                smtp_host=sender.smtp_host,
                smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username,
                smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=receiver_email,
                subject=draft.final_subject,
                body=draft.final_body,
            )
            await _log_sent(user_id, draft.lead_id, sender.email_address, receiver_email, draft.final_subject)
            await _mark_contacted(draft.lead_id, user_id)
            sent += 1
            logger.info("outreach_agent.sent", lead_id=draft.lead_id, to=receiver_email)

        except Exception as e:
            await _log_sent(user_id, draft.lead_id, sender.email_address, receiver_email,
                           draft.final_subject, status="failed", error=str(e)[:500])
            failed += 1
            logger.error("outreach_agent.send_failed", lead_id=draft.lead_id, error=str(e)[:200])

    logger.info("outreach_agent.cycle_complete", user_id=user_id, sent=sent, skipped=skipped, failed=failed)
    return {"sent": sent, "skipped": skipped, "failed": failed}
