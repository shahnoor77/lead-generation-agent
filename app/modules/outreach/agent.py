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
import hashlib
import imaplib
import json
import os
import re
import secrets
import smtplib
import ssl
from functools import partial
from datetime import datetime, date, timedelta
import time
from email import message_from_bytes
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, make_msgid

from sqlmodel import select
from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    FinalizedDraftRecord,
    OutreachSentRecord,
    OutreachReplyRecord,
    MeetingHandoffRecord,
    SenderEmailAccountRecord,
    LeadLifecycleRecord,
)
from app.schemas.lifecycle import LeadLifecycleStatus
from app.modules.outreach.email_sanitize import clean_outreach_copy
from app.utils.encryption import decrypt
from app.utils.llm_client import llm_chat
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Inbox scanning (recent mail, threading) ──────────────────────────────────
_IMAP_LOOKBACK_DAYS = int(os.environ.get("OUTREACH_IMAP_LOOKBACK_DAYS", "21"))
_IMAP_MAX_MESSAGES = int(os.environ.get("OUTREACH_IMAP_MAX_MESSAGES_PER_POLL", "400"))
# Concurrent handlers per IMAP poll — faster auto-replies without extra IMAP round-trips.
_INBOX_PARALLEL_WORKERS = max(1, min(32, int(os.environ.get("OUTREACH_INBOX_PARALLEL_WORKERS", "5"))))

# Skip IMAP polls for a user after fatal auth failures (reduces Gmail lockouts / log spam).
_OUTREACH_IMAP_AUTH_COOLDOWN_SEC = float(os.environ.get("OUTREACH_IMAP_AUTH_COOLDOWN_SEC", "900"))
_imap_auth_cooldown_until: dict[str, float] = {}

# ── SMTP sender ───────────────────────────────────────────────────────────────

def _domain_from_email(addr: str) -> str:
    return addr.split("@")[-1].strip().lower() if "@" in addr else "localhost"


def _imap_auth_error(e: BaseException) -> bool:
    """Heuristic: IMAP login rejected (bad password / app password / account security)."""
    blob = f"{e!r} {e}".upper()
    return (
        "AUTHENTICATIONFAILED" in blob
        or "INVALID CREDENTIALS" in blob
        or "535" in blob
        or "AUTHENTICATION FAILED" in blob
    )


def _imap_in_auth_cooldown(user_id: str) -> bool:
    until = _imap_auth_cooldown_until.get(user_id)
    return until is not None and time.time() < until


def _set_imap_auth_cooldown(user_id: str) -> None:
    _imap_auth_cooldown_until[user_id] = time.time() + _OUTREACH_IMAP_AUTH_COOLDOWN_SEC


def _format_message_id_header(mid: str | None) -> str | None:
    if not mid or not str(mid).strip():
        return None
    s = str(mid).strip()
    if s.startswith("<") and s.endswith(">"):
        return s
    return f"<{s.strip('<>')}>"


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
    *,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """
    Synchronous SMTP send — run in executor to avoid blocking.
    Returns the Message-ID we placed on the outbound mail (for IMAP threading).
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg_id = make_msgid(idstring=secrets.token_hex(10), domain=_domain_from_email(from_email))
    msg["Message-ID"] = msg_id
    irt = _format_message_id_header(in_reply_to)
    if irt:
        msg["In-Reply-To"] = irt
    if references:
        msg["References"] = references.strip()
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
    return msg_id


async def _send_email_async(
    smtp_host: str, smtp_port: int, smtp_username: str,
    smtp_password: str, use_tls: bool,
    from_email: str, from_name: str,
    to_email: str, subject: str, body: str,
    *,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(
            _send_smtp,
            smtp_host, smtp_port, smtp_username, smtp_password, use_tls,
            from_email, from_name, to_email, subject, body,
            in_reply_to=in_reply_to,
            references=references,
        ),
    )


# ── Dedup check ───────────────────────────────────────────────────────────────

async def _already_sent(user_id: str, lead_id: str, receiver_email: str) -> bool:
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

async def _get_sent_today(user_id: str, sender_email: str) -> int:
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
    user_id: str, lead_id: str, sender_email: str,
    receiver_email: str, subject: str,
    status: str = "sent", error: str | None = None,
    campaign_stage: str = "initial",
    outbound_message_id: str | None = None,
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
            campaign_stage=campaign_stage,
            error_message=error,
            outbound_message_id=outbound_message_id.strip() if outbound_message_id else None,
        ))
        await session.commit()


# ── Lifecycle updates ──────────────────────────────────────────────────────────

async def _set_lifecycle_status(
    lead_id: str,
    status: LeadLifecycleStatus,
    updated_by: str,
    notes: str | None = None,
) -> None:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        lc = await session.get(LeadLifecycleRecord, lead_id)
        if lc:
            lc.current_status = status.value
            lc.updated_by = updated_by
            lc.status_updated_at = now
            lc.notes = notes
            session.add(lc)
            from app.storage.models import LeadLifecycleHistoryRecord
            session.add(LeadLifecycleHistoryRecord(
                lead_id=lead_id,
                status=status.value,
                changed_at=now,
                changed_by=updated_by,
                notes=notes,
            ))
            await session.commit()


async def _mark_contacted(lead_id: str, user_id: str) -> None:
    await _set_lifecycle_status(lead_id, LeadLifecycleStatus.CONTACTED, "outreach_agent")


def _imap_host_from_smtp(smtp_host: str) -> str:
    if smtp_host.startswith("smtp."):
        return "imap." + smtp_host[len("smtp."):]
    return smtp_host


def _decode_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return raw


def _extract_text_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                return _decode_text(part.get_payload(decode=True))
        return ""
    return _decode_text(msg.get_payload(decode=True))


def _classify_reply_intent(text: str) -> str:
    normalized = (text or "").lower()
    negative_markers = ["not interested", "stop", "unsubscribe", "remove me", "do not contact", "don't contact", "no thanks"]
    positive_markers = ["interested", "sounds good", "let's talk", "book", "meeting", "call me", "share details"]
    if any(m in normalized for m in negative_markers):
        return "negative"
    if any(m in normalized for m in positive_markers):
        return "positive"
    return "neutral"


def _build_followup_subject(initial_subject: str, followup_number: int) -> str:
    """Generate subject for follow-up email."""
    if initial_subject.lower().startswith("re:"):
        return initial_subject
    return f"Re: {initial_subject} (follow-up {followup_number})"


def _build_followup_body(draft: FinalizedDraftRecord, followup_number: int) -> str:
    """
    Generate follow-up email with professional greeting.
    Uses the same greeting logic as the initial email.
    """
    company_name = draft.company_name
    sender_name = (draft.sender_name or "Our Team").strip()
    
    # Professional greeting — hardcoded, never auto-detected
    # Priority: receiver_name + role > receiver_name only > company team > generic
    receiver_name = (draft.receiver_name or "").strip()
    receiver_role = (draft.receiver_role or "").strip()
    
    if receiver_role and receiver_name:
        # Extract last name from receiver_name
        name_parts = receiver_name.split()
        last_name = name_parts[-1] if name_parts else receiver_name
        greeting = f"Dear {receiver_role} {last_name},"
    elif receiver_name:
        # Just first name
        name_parts = receiver_name.split()
        first_name = name_parts[0] if name_parts else receiver_name
        greeting = f"Dear {first_name},"
    else:
        # No name — use company or generic
        greeting = f"Dear {company_name} Team," if company_name else "To Whom It May Concern,"
    
    body = (
        f"{greeting}\n\n"
        f"I wanted to follow up on my previous email regarding operational efficiency and coordination "
        f"improvements for {company_name}.\n\n"
        f"I understand things move quickly on your end. If a brief 15-minute conversation would be helpful "
        f"to explore how similar organizations have tackled this, I'm happy to make time.\n\n"
        f"Best regards,\n{sender_name}"
    )
    return body


async def _build_auto_reply_body(
    original_subject: str,
    prospect_reply: str,
    sender_name: str,
    company_name: str,
    receiver_name: str = "",
    receiver_role: str = "",
) -> str:
    """
    Generate professional auto-reply to prospect.
    Uses hardcoded formal greeting.
    """
    receiver_name = (receiver_name or "").strip()
    receiver_role = (receiver_role or "").strip()
    
    # Professional greeting
    if receiver_role and receiver_name:
        name_parts = receiver_name.split()
        last_name = name_parts[-1] if name_parts else receiver_name
        greeting = f"Dear {receiver_role} {last_name},"
    elif receiver_name:
        name_parts = receiver_name.split()
        first_name = name_parts[0] if name_parts else receiver_name
        greeting = f"Dear {first_name},"
    else:
        greeting = f"Dear {company_name} Team," if company_name else "To Whom It May Concern,"
    
    body = (
        f"{greeting}\n\n"
        f"Thank you for your reply. I appreciate you taking the time to get back to me.\n\n"
        f"I'd love to continue this conversation at your convenience. If you'd like to schedule "
        f"a brief 15-minute call to explore how we can help {company_name}, please let me know "
        f"what works best for your calendar.\n\n"
        f"Best regards,\n{sender_name}"
    )
    return body


# ──────────────────────────────────────────────────────────────────────────────
# THREADING FIX: Follow-ups now properly reference the initial send
# ──────────────────────────────────────────────────────────────────────────────

async def run_outreach_job(user_id: str) -> dict:
    """
    Execute one outreach job cycle for a user.
    
    Logic:
      1. Load approved finalized drafts
      2. For each draft:
         - If NO initial send → send initial email
         - If initial sent + NO reply + elapsed >= 48h → send follow-up (thread to initial)
         - If follow-ups sent >= 4 times AND no reply + 7 days elapsed → mark LOST
         - If positive reply → extract meeting details + handoff
         - If negative reply → mark LOST
         - If neutral reply → send auto-reply
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

    smtp_password = decrypt(sender.smtp_password_encrypted)

    # Inbox replies: run regardless of send window
    reply_summary: dict = {"processed": 0, "closed": 0, "auto_replied": 0}
    if outreach_cfg.reply_check_enabled:
        reply_summary = await _process_inbox_replies(user_id, sender, smtp_password)

    # Outbound sends respect send window only
    if not _in_send_window(outreach_cfg.send_window_start, outreach_cfg.send_window_end):
        logger.info("outreach_agent.outside_window", user_id=user_id)
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "outside_send_window", "replies": reply_summary}

    # Check daily limit
    sent_today = await _get_sent_today(user_id, sender.email_address)
    remaining = min(sender.daily_limit, outreach_cfg.daily_send_limit) - sent_today
    if remaining <= 0:
        logger.info("outreach_agent.daily_limit_reached", user_id=user_id, sent_today=sent_today)
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "daily_limit_reached", "replies": reply_summary}

    # Load approved finalized drafts for this user
    async with AsyncSessionLocal() as session:
        from app.storage.models import PipelineRunRecord
        runs_result = await session.execute(
            select(PipelineRunRecord.id).where(PipelineRunRecord.user_id == user_id)
        )
        run_ids = [r[0] for r in runs_result.all()]

        if not run_ids:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "no_runs", "replies": reply_summary}

        drafts_result = await session.execute(
            select(FinalizedDraftRecord)
            .where(FinalizedDraftRecord.pipeline_run_id.in_(run_ids))
            .where(FinalizedDraftRecord.approval_status == "APPROVED")
        )
        approved_drafts = list(drafts_result.scalars().all())

    sent = skipped = failed = 0

    from app.services.sandbox_outreach import (
        SandboxConfigError,
        resolve_smtp_receiver,
        is_sandbox_pipeline_run,
    )

    for draft in approved_drafts:
        if sent >= remaining:
            break

        natural_receiver = (draft.receiver_email or "").strip()
        if not natural_receiver:
            skipped += 1
            continue

        sandbox_pipeline = await is_sandbox_pipeline_run(user_id, draft.pipeline_run_id)
        try:
            receiver_email = await resolve_smtp_receiver(
                user_id,
                draft.lead_id,
                natural_receiver,
                sandbox_pipeline=sandbox_pipeline,
            )
        except SandboxConfigError as err:
            logger.warning(
                "outreach_agent.sandbox_resolve_skipped",
                lead_id=draft.lead_id,
                error=str(err),
            )
            skipped += 1
            continue

        # Skip closed leads (replied/won/lost/archived)
        async with AsyncSessionLocal() as session:
            lifecycle = await session.get(LeadLifecycleRecord, draft.lead_id)
        if lifecycle and lifecycle.current_status in {
            LeadLifecycleStatus.REPLIED.value,
            LeadLifecycleStatus.MEETING_SCHEDULED.value,
            LeadLifecycleStatus.WON.value,
            LeadLifecycleStatus.LOST.value,
            LeadLifecycleStatus.ARCHIVED.value,
        }:
            skipped += 1
            continue

        # ── Sent history for this lead ────────────────────────────────────────
        async with AsyncSessionLocal() as session:
            sent_result = await session.execute(
                select(OutreachSentRecord)
                .where(OutreachSentRecord.user_id == user_id)
                .where(OutreachSentRecord.lead_id == draft.lead_id)
                .where(OutreachSentRecord.receiver_email == receiver_email)
                .where(OutreachSentRecord.status == "sent")
                .order_by(OutreachSentRecord.sent_at.desc())
            )
            sent_rows = list(sent_result.scalars().all())

            # Check if any reply received (positive/negative/neutral)
            reply_result = await session.execute(
                select(OutreachReplyRecord)
                .where(OutreachReplyRecord.user_id == user_id)
                .where(OutreachReplyRecord.lead_id == draft.lead_id)
                .where(OutreachReplyRecord.receiver_email == receiver_email)
            )
            reply_rows = list(reply_result.scalars().all())

        has_reply = len(reply_rows) > 0
        latest_reply = reply_rows[0] if reply_rows else None
        
        followup_count = sum(1 for r in sent_rows if r.campaign_stage == "followup")
        initial_count = sum(1 for r in sent_rows if r.campaign_stage == "initial")
        has_initial = initial_count > 0
        last_sent = sent_rows[0] if sent_rows else None

        should_send = False
        subject = draft.final_subject
        body = draft.final_body
        stage = "initial"
        in_reply_to_mid: str | None = None
        references: str | None = None

        # ── Logic: Initial send ───────────────────────────────────────────────
        if not has_initial:
            should_send = True

        # ── Logic: Follow-ups (48h interval) ──────────────────────────────────
        elif outreach_cfg.followup_enabled and not has_reply:
            max_attempts = outreach_cfg.followup_max_attempts  # default: 4
            
            # Check if we've hit max follow-ups
            if followup_count >= max_attempts:
                # Check if 7 days have passed since initial send
                initial_send = next((r for r in sent_rows if r.campaign_stage == "initial"), None)
                if initial_send:
                    elapsed_since_initial = datetime.utcnow() - initial_send.sent_at
                    if elapsed_since_initial >= timedelta(days=7):
                        # Mark as LOST — no reply after 7 days + max follow-ups
                        await _set_lifecycle_status(
                            draft.lead_id,
                            LeadLifecycleStatus.LOST,
                            "followup_agent",
                            notes=f"No reply after {followup_count} follow-ups over 7+ days. Lead marked lost.",
                        )
                        logger.info(
                            "outreach_agent.lead_marked_lost",
                            lead_id=draft.lead_id,
                            reason="no_reply_7days",
                            followup_count=followup_count,
                        )
                        skipped += 1
                        continue
            
            # Check time since last send for follow-up timing
            if last_sent:
                elapsed = datetime.utcnow() - last_sent.sent_at
                if elapsed >= timedelta(hours=outreach_cfg.followup_interval_hours):
                    if followup_count < max_attempts:
                        should_send = True
                        stage = "followup"
                        subject = _build_followup_subject(draft.final_subject, followup_count + 1)
                        body = _build_followup_body(draft, followup_count + 1)
                        
                        # ── THREADING FIX: Follow-up threads back to initial send ────
                        initial_send = next((r for r in sent_rows if r.campaign_stage == "initial"), None)
                        if initial_send and initial_send.outbound_message_id:
                            in_reply_to_mid = initial_send.outbound_message_id.strip()
                            # Build references chain: initial + all follow-ups
                            refs_chain = [in_reply_to_mid]
                            for fo in [r for r in sent_rows if r.campaign_stage == "followup"]:
                                if fo.outbound_message_id and fo.outbound_message_id not in refs_chain:
                                    refs_chain.append(fo.outbound_message_id.strip())
                            references = " ".join(f"<{_canonical_mid(mid)}>" for mid in refs_chain if mid)

        if not should_send:
            skipped += 1
            continue

        subject, body = clean_outreach_copy(subject, body, for_send=True)

        # Send
        try:
            outbound_mid = await _send_email_async(
                smtp_host=sender.smtp_host,
                smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username,
                smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=receiver_email,
                subject=subject,
                body=body,
                in_reply_to=in_reply_to_mid,
                references=references,
            )
            await _log_sent(
                user_id, draft.lead_id, sender.email_address, receiver_email, subject,
                campaign_stage=stage,
                outbound_message_id=outbound_mid,
            )
            await _mark_contacted(draft.lead_id, user_id)
            sent += 1
            logger.info(
                "outreach_agent.sent",
                lead_id=draft.lead_id,
                to=receiver_email,
                stage=stage,
                followup_num=(followup_count + 1 if stage == "followup" else 0),
            )

        except Exception as e:
            await _log_sent(
                user_id, draft.lead_id, sender.email_address, receiver_email,
                subject, status="failed", error=str(e)[:500], campaign_stage=stage,
            )
            failed += 1
            logger.error("outreach_agent.send_failed", lead_id=draft.lead_id, error=str(e)[:200])

    logger.info(
        "outreach_agent.cycle_complete",
        user_id=user_id,
        sent=sent,
        skipped=skipped,
        failed=failed,
        replies_processed=reply_summary["processed"],
    )
    return {"sent": sent, "skipped": skipped, "failed": failed, "replies": reply_summary}
