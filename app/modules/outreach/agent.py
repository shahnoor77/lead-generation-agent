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
import imaplib
import smtplib
import ssl
from datetime import datetime, date, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr

from sqlmodel import select
from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    FinalizedDraftRecord,
    OutreachSentRecord,
    OutreachReplyRecord,
    SenderEmailAccountRecord,
    LeadLifecycleRecord,
)
from app.schemas.lifecycle import LeadLifecycleStatus
from app.utils.encryption import decrypt
from app.utils.llm_client import llm_chat
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
    campaign_stage: str = "initial",
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


async def _mark_contacted(lead_id: str, user_id: int) -> None:
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
    if initial_subject.lower().startswith("re:"):
        return initial_subject
    return f"Re: {initial_subject} (follow-up {followup_number})"


def _build_followup_body(draft: FinalizedDraftRecord, followup_number: int) -> str:
    return (
        f"Hi {draft.receiver_name},\n\n"
        f"Following up on my previous email in case it got buried. "
        f"I thought this might still be relevant for {draft.company_name}.\n\n"
        "If helpful, I can share a short, tailored plan in one call.\n\n"
        f"Best,\n{draft.sender_name}"
    )


async def _generate_reply_body(
    draft: FinalizedDraftRecord,
    reply_body: str,
    user_id: int,
) -> str:
    prompt = (
        "You are a B2B sales assistant. Draft a concise, polite email response "
        "to the prospect message. Keep it under 150 words, clear next step, no hype.\n\n"
        f"Prospect message:\n{reply_body}\n\n"
        f"Our original context: company={draft.company_name}, sender={draft.sender_name}, receiver={draft.receiver_name}"
    )
    try:
        response = await llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=220,
            temperature=0.2,
            user_id=user_id,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or "Thanks for your reply. Happy to share more details on a quick call."
    except Exception:
        return "Thanks for your reply. Happy to share more details on a quick call."


async def _already_processed_reply(user_id: int, message_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachReplyRecord)
            .where(OutreachReplyRecord.user_id == user_id)
            .where(OutreachReplyRecord.message_id == message_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


async def _save_reply(
    user_id: int,
    lead_id: str,
    receiver_email: str,
    message_id: str,
    subject: str,
    body: str,
    intent: str,
) -> None:
    async with AsyncSessionLocal() as session:
        session.add(OutreachReplyRecord(
            user_id=user_id,
            lead_id=lead_id,
            receiver_email=receiver_email,
            message_id=message_id,
            reply_subject=subject,
            reply_body=body[:4000],
            intent=intent,
        ))
        await session.commit()


async def _get_last_outbound_by_receiver(user_id: int, receiver_email: str) -> OutreachSentRecord | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == user_id)
            .where(OutreachSentRecord.receiver_email == receiver_email)
            .where(OutreachSentRecord.status == "sent")
            .order_by(OutreachSentRecord.sent_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def _fetch_inbox_messages(
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    use_ssl: bool,
) -> list[dict]:
    messages: list[dict] = []
    client = imaplib.IMAP4_SSL(imap_host, imap_port) if use_ssl else imaplib.IMAP4(imap_host, imap_port)
    try:
        client.login(username, password)
        client.select("INBOX")
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            return messages
        for num in data[0].split():
            status, msg_data = client.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = message_from_bytes(raw)
            frm = parseaddr(msg.get("From", ""))[1].lower()
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            message_id = (msg.get("Message-ID", "") or "").strip()
            body = _extract_text_body(msg).strip()
            messages.append({
                "from_email": frm,
                "subject": subject,
                "message_id": message_id,
                "body": body,
            })
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return messages


async def _process_inbox_replies(
    user_id: int,
    sender: SenderEmailAccountRecord,
    smtp_password: str,
) -> dict:
    imap_host = sender.imap_host or _imap_host_from_smtp(sender.smtp_host)
    imap_port = sender.imap_port or 993
    imap_username = sender.imap_username or sender.smtp_username
    imap_password = decrypt(sender.imap_password_encrypted) if sender.imap_password_encrypted else smtp_password
    processed = 0
    closed = 0
    auto_replied = 0
    try:
        loop = asyncio.get_event_loop()
        inbox_messages = await loop.run_in_executor(
            None,
            _fetch_inbox_messages,
            imap_host,
            imap_port,
            imap_username,
            imap_password,
            sender.imap_use_ssl,
        )
    except Exception as e:
        logger.warning("outreach_agent.imap_failed", user_id=user_id, error=str(e)[:200])
        return {"processed": 0, "closed": 0, "auto_replied": 0, "reason": "imap_failed"}

    for msg in inbox_messages:
        from_email = (msg.get("from_email") or "").lower()
        if not from_email:
            continue
        message_id = (msg.get("message_id") or "").strip() or f"generated:{from_email}:{hash(msg.get('body', ''))}"
        if await _already_processed_reply(user_id, message_id):
            continue

        last_outbound = await _get_last_outbound_by_receiver(user_id, from_email)
        if not last_outbound:
            continue

        body = msg.get("body", "").strip()
        intent = _classify_reply_intent(body)
        await _save_reply(
            user_id=user_id,
            lead_id=last_outbound.lead_id,
            receiver_email=from_email,
            message_id=message_id,
            subject=msg.get("subject", ""),
            body=body,
            intent=intent,
        )
        processed += 1

        if intent == "negative":
            await _set_lifecycle_status(
                last_outbound.lead_id,
                LeadLifecycleStatus.LOST,
                "followup_agent",
                notes="Prospect responded negatively (not interested / opt-out).",
            )
            closed += 1
            continue

        await _set_lifecycle_status(
            last_outbound.lead_id,
            LeadLifecycleStatus.REPLIED,
            "followup_agent",
            notes=f"Prospect replied ({intent}).",
        )
        if intent == "neutral":
            async with AsyncSessionLocal() as session:
                draft = await session.get(FinalizedDraftRecord, last_outbound.lead_id)
            if draft:
                auto_body = await _generate_reply_body(draft, body, user_id)
                try:
                    await _send_email_async(
                        smtp_host=sender.smtp_host,
                        smtp_port=sender.smtp_port,
                        smtp_username=sender.smtp_username,
                        smtp_password=smtp_password,
                        use_tls=sender.use_tls,
                        from_email=sender.email_address,
                        from_name=sender.display_name or sender.email_address,
                        to_email=from_email,
                        subject=msg.get("subject", "") or f"Re: {draft.final_subject}",
                        body=auto_body,
                    )
                    await _log_sent(
                        user_id,
                        last_outbound.lead_id,
                        sender.email_address,
                        from_email,
                        msg.get("subject", "") or f"Re: {draft.final_subject}",
                        campaign_stage="reply",
                    )
                    auto_replied += 1
                except Exception as e:
                    logger.warning("outreach_agent.auto_reply_failed", lead_id=last_outbound.lead_id, error=str(e)[:200])
    return {"processed": processed, "closed": closed, "auto_replied": auto_replied}


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

    reply_summary = {"processed": 0, "closed": 0, "auto_replied": 0}
    if outreach_cfg.reply_check_enabled:
        reply_summary = await _process_inbox_replies(user_id, sender, smtp_password)

    for draft in approved_drafts:
        if sent >= remaining:
            break

        receiver_email = draft.receiver_email
        if not receiver_email:
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

        # Initial send or follow-up decision
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

        followup_count = sum(1 for r in sent_rows if r.campaign_stage == "followup")
        has_initial = any(r.campaign_stage == "initial" for r in sent_rows)
        last_sent = sent_rows[0] if sent_rows else None

        should_send = False
        subject = draft.final_subject
        body = draft.final_body
        stage = "initial"

        if not has_initial:
            should_send = True
        elif outreach_cfg.followup_enabled:
            max_attempts = outreach_cfg.followup_max_attempts
            if followup_count >= max_attempts:
                await _set_lifecycle_status(
                    draft.lead_id,
                    LeadLifecycleStatus.LOST,
                    "followup_agent",
                    notes=f"No reply after {followup_count} follow-ups.",
                )
                skipped += 1
                continue
            if not last_sent:
                skipped += 1
                continue
            elapsed = datetime.utcnow() - last_sent.sent_at
            if elapsed >= timedelta(hours=outreach_cfg.followup_interval_hours):
                should_send = True
                stage = "followup"
                subject = _build_followup_subject(draft.final_subject, followup_count + 1)
                body = _build_followup_body(draft, followup_count + 1)

        if not should_send:
            skipped += 1
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
                subject=subject,
                body=body,
            )
            await _log_sent(
                user_id, draft.lead_id, sender.email_address, receiver_email, subject,
                campaign_stage=stage,
            )
            await _mark_contacted(draft.lead_id, user_id)
            sent += 1
            logger.info("outreach_agent.sent", lead_id=draft.lead_id, to=receiver_email, stage=stage)

        except Exception as e:
            await _log_sent(user_id, draft.lead_id, sender.email_address, receiver_email,
                           subject, status="failed", error=str(e)[:500], campaign_stage=stage)
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
