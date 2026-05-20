"""
Outreach Agent — sends approved email drafts via SMTP and manages conversational replies.

Flow per job run:
  1. Poll IMAP inbox → process replies via conversation manager
  2. Load approved finalized drafts
  3. For each draft: send initial or follow-up email
  4. Follow-up threading, daily limits, send window all enforced

Conversation memory:
  - One ConversationThread per (user_id, lead_id, receiver_email)
  - Every inbound/outbound message appended to thread
  - LLM generates contextual replies using rolling summary + recent turns
  - Positive reply → extract meeting details → MeetingHandoffRecord → WON
  - Negative reply → close thread → LOST
  - Neutral reply → LLM contextual reply → continue conversation
"""

from __future__ import annotations
import asyncio
import imaplib
import os
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
    ConversationThreadRecord,
)
from app.schemas.lifecycle import LeadLifecycleStatus
from app.modules.outreach.email_sanitize import clean_outreach_copy
from app.modules.outreach.conversation_manager import (
    get_or_create_thread,
    append_message,
    generate_conversational_reply,
    extract_meeting_details,
    maybe_summarize,
    close_thread,
    update_thread_status,
)
from app.utils.encryption import decrypt
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_IMAP_LOOKBACK_DAYS = int(os.environ.get("OUTREACH_IMAP_LOOKBACK_DAYS", "21"))
_IMAP_MAX_MESSAGES = int(os.environ.get("OUTREACH_IMAP_MAX_MESSAGES_PER_POLL", "400"))
_INBOX_PARALLEL_WORKERS = max(1, min(32, int(os.environ.get("OUTREACH_INBOX_PARALLEL_WORKERS", "5"))))
_OUTREACH_IMAP_AUTH_COOLDOWN_SEC = float(os.environ.get("OUTREACH_IMAP_AUTH_COOLDOWN_SEC", "900"))
_imap_auth_cooldown_until: dict[str, float] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _domain_from_email(addr: str) -> str:
    return addr.split("@")[-1].strip().lower() if "@" in addr else "localhost"


def _canonical_mid(mid: str) -> str:
    return mid.strip().strip("<>").strip()


def _format_message_id_header(mid: str | None) -> str | None:
    if not mid or not str(mid).strip():
        return None
    s = str(mid).strip()
    return s if (s.startswith("<") and s.endswith(">")) else f"<{s.strip('<>')}>"


def _imap_auth_error(e: BaseException) -> bool:
    blob = f"{e!r} {e}".upper()
    return any(x in blob for x in ("AUTHENTICATIONFAILED", "INVALID CREDENTIALS", "535", "AUTHENTICATION FAILED"))


def _imap_in_auth_cooldown(user_id: str) -> bool:
    until = _imap_auth_cooldown_until.get(user_id)
    return until is not None and time.time() < until


def _set_imap_auth_cooldown(user_id: str) -> None:
    _imap_auth_cooldown_until[user_id] = time.time() + _OUTREACH_IMAP_AUTH_COOLDOWN_SEC


def _imap_host_from_smtp(smtp_host: str) -> str:
    return ("imap." + smtp_host[len("smtp."):]) if smtp_host.startswith("smtp.") else smtp_host


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
    negative = ["not interested", "stop", "unsubscribe", "remove me", "do not contact", "don't contact", "no thanks"]
    positive = ["interested", "sounds good", "let's talk", "book", "meeting", "call me", "share details", "yes", "would love"]
    if any(m in normalized for m in negative):
        return "negative"
    if any(m in normalized for m in positive):
        return "positive"
    return "neutral"


def _in_send_window(window_start: str, window_end: str) -> bool:
    now = datetime.utcnow().strftime("%H:%M")
    return window_start <= now <= window_end


def _build_followup_subject(initial_subject: str, followup_number: int) -> str:
    if initial_subject.lower().startswith("re:"):
        return initial_subject
    return f"Re: {initial_subject} (follow-up {followup_number})"

def _build_followup_body(draft: FinalizedDraftRecord, followup_number: int) -> str:
    company_name = draft.company_name
    sender_name = (draft.sender_name or "Our Team").strip()
    receiver_name = (draft.receiver_name or "").strip()
    receiver_role = (draft.receiver_role or "").strip()
    if receiver_role and receiver_name:
        last_name = receiver_name.split()[-1]
        greeting = f"Dear {receiver_role} {last_name},"
    elif receiver_name:
        greeting = f"Dear {receiver_name.split()[0]},"
    else:
        greeting = f"Dear {company_name} Team," if company_name else "To Whom It May Concern,"
    return (
        f"{greeting}\n\n"
        f"I wanted to follow up on my previous email regarding operational efficiency improvements "
        f"for {company_name}.\n\n"
        f"I understand things move quickly. If a brief 15-minute conversation would be helpful "
        f"to explore how similar organizations have tackled this, I'm happy to make time.\n\n"
        f"Best regards,\n{sender_name}"
    )


def _fallback_reply_body(
    sender_name: str, company_name: str,
    receiver_name: str = "", receiver_role: str = "",
) -> str:
    receiver_name = (receiver_name or "").strip()
    receiver_role = (receiver_role or "").strip()
    if receiver_role and receiver_name:
        greeting = f"Dear {receiver_role} {receiver_name.split()[-1]},"
    elif receiver_name:
        greeting = f"Dear {receiver_name.split()[0]},"
    else:
        greeting = f"Dear {company_name} Team," if company_name else "To Whom It May Concern,"
    return (
        f"{greeting}\n\n"
        f"Thank you for your reply. I appreciate you taking the time to get back to me.\n\n"
        f"I'd love to continue this conversation. Could we schedule a brief 15-minute call "
        f"to explore how we can help {company_name}? Please let me know what works best.\n\n"
        f"Best regards,\n{sender_name}"
    )


# ── SMTP ──────────────────────────────────────────────────────────────────────

def _send_smtp(
    smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    use_tls: bool, from_email: str, from_name: str,
    to_email: str, subject: str, body: str,
    *, in_reply_to: str | None = None, references: str | None = None,
) -> str:
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
            server.ehlo(); server.starttls(context=context)
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())
    return msg_id


async def _send_email_async(
    smtp_host: str, smtp_port: int, smtp_username: str, smtp_password: str,
    use_tls: bool, from_email: str, from_name: str,
    to_email: str, subject: str, body: str,
    *, in_reply_to: str | None = None, references: str | None = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_send_smtp, smtp_host, smtp_port, smtp_username, smtp_password,
                use_tls, from_email, from_name, to_email, subject, body,
                in_reply_to=in_reply_to, references=references),
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _already_sent(user_id: str, lead_id: str, receiver_email: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == user_id)
            .where(OutreachSentRecord.lead_id == lead_id)
            .where(OutreachSentRecord.receiver_email == receiver_email)
        )
        return result.scalar_one_or_none() is not None


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


async def _log_sent(
    user_id: str, lead_id: str, sender_email: str,
    receiver_email: str, subject: str,
    status: str = "sent", error: str | None = None,
    campaign_stage: str = "initial", outbound_message_id: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        session.add(OutreachSentRecord(
            user_id=user_id, lead_id=lead_id, finalized_draft_id=lead_id,
            sender_email=sender_email, receiver_email=receiver_email,
            subject=subject, status=status, campaign_stage=campaign_stage,
            error_message=error,
            outbound_message_id=outbound_message_id.strip() if outbound_message_id else None,
        ))
        await session.commit()


async def _set_lifecycle_status(
    lead_id: str, status: LeadLifecycleStatus,
    updated_by: str, notes: str | None = None,
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
                lead_id=lead_id, status=status.value,
                changed_at=now, changed_by=updated_by, notes=notes,
            ))
            await session.commit()


async def _mark_contacted(lead_id: str, user_id: str) -> None:
    await _set_lifecycle_status(lead_id, LeadLifecycleStatus.CONTACTED, "outreach_agent")


# ── IMAP fetch (sync, runs in executor) ───────────────────────────────────────

def _fetch_imap_messages(
    host: str, port: int, username: str, password: str,
    use_ssl: bool, lookback_days: int, max_messages: int,
) -> list[bytes]:
    since_date = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    mail = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    mail.login(username, password)
    mail.select("INBOX")
    _, data = mail.search(None, f'(SINCE "{since_date}")')
    msg_ids = data[0].split() if data and data[0] else []
    msg_ids = msg_ids[-max_messages:][::-1]
    messages = []
    for mid in msg_ids:
        try:
            _, msg_data = mail.fetch(mid, "(RFC822)")
            if msg_data and msg_data[0]:
                messages.append(msg_data[0][1])
        except Exception:
            continue
    mail.logout()
    return messages


# ── Conversational reply sender ───────────────────────────────────────────────

async def _send_conversational_reply(
    thread: ConversationThreadRecord,
    lead_id: str, user_id: str,
    sender: SenderEmailAccountRecord, smtp_password: str,
    reply_body: str, original_subject: str,
    sender_name: str, sender_role: str, sender_company: str,
    receiver_name: str, receiver_role: str, company_name: str,
    in_reply_to_mid: str | None,
) -> None:
    await maybe_summarize(thread, sender_name, sender_company, receiver_name, user_id=user_id)
    try:
        reply_subject, reply_body_text = await generate_conversational_reply(
            thread=thread, latest_reply_body=reply_body,
            original_subject=original_subject,
            sender_name=sender_name, sender_role=sender_role, sender_company=sender_company,
            receiver_name=receiver_name, receiver_role=receiver_role, user_id=user_id,
        )
    except Exception as e:
        logger.warning("conversation.llm_reply_failed", lead_id=lead_id, error=str(e)[:200])
        reply_subject = f"Re: {original_subject}"
        reply_body_text = _fallback_reply_body(sender_name, company_name, receiver_name, receiver_role)

    try:
        outbound_mid = await _send_email_async(
            smtp_host=sender.smtp_host, smtp_port=sender.smtp_port,
            smtp_username=sender.smtp_username, smtp_password=smtp_password,
            use_tls=sender.use_tls,
            from_email=sender.email_address,
            from_name=sender.display_name or sender.email_address,
            to_email=thread.receiver_email,
            subject=reply_subject, body=reply_body_text,
            in_reply_to=in_reply_to_mid,
        )
        await _log_sent(user_id, lead_id, sender.email_address, thread.receiver_email,
                        reply_subject, campaign_stage="reply", outbound_message_id=outbound_mid)
        await append_message(
            thread_id=thread.id, user_id=user_id, lead_id=lead_id,
            direction="outbound", body=reply_body_text,
            subject=reply_subject, message_id=outbound_mid,
        )
        logger.info("conversation.reply_sent", lead_id=lead_id, to=thread.receiver_email)
    except Exception as e:
        logger.error("conversation.reply_send_failed", lead_id=lead_id, error=str(e)[:200])


# ── Single reply handler ──────────────────────────────────────────────────────

async def _handle_reply_message(
    raw_msg: bytes, user_id: str,
    sender: SenderEmailAccountRecord, smtp_password: str,
    mid_to_sent: dict[str, OutreachSentRecord],
    seen_reply_ids: set[str],
) -> str:
    try:
        msg = message_from_bytes(raw_msg)
    except Exception:
        return "skipped"

    from_addr = parseaddr(msg.get("From", ""))[1].lower()
    if from_addr == sender.email_address.lower():
        return "skipped"

    inbound_mid = (msg.get("Message-ID") or "").strip()
    if inbound_mid and _canonical_mid(inbound_mid) in seen_reply_ids:
        return "skipped"

    in_reply_to = _canonical_mid(msg.get("In-Reply-To") or "")
    ref_mids = [_canonical_mid(r) for r in (msg.get("References") or "").split() if r.strip()]

    matched_sent: OutreachSentRecord | None = None
    for candidate in [in_reply_to] + ref_mids:
        if candidate in mid_to_sent:
            matched_sent = mid_to_sent[candidate]
            break
    if not matched_sent:
        return "skipped"

    lead_id = matched_sent.lead_id
    receiver_email = from_addr
    body = _extract_text_body(msg)
    if not body or not body.strip():
        return "skipped"

    subject = str(make_header(decode_header(msg.get("Subject", "Re: (no subject)"))))
    intent = _classify_reply_intent(body)

    # Dedup + save reply record
    async with AsyncSessionLocal() as session:
        if inbound_mid:
            dup = await session.execute(
                select(OutreachReplyRecord)
                .where(OutreachReplyRecord.message_id == inbound_mid)
                .where(OutreachReplyRecord.user_id == user_id)
            )
            if dup.scalar_one_or_none():
                return "skipped"
        session.add(OutreachReplyRecord(
            user_id=user_id, lead_id=lead_id, receiver_email=receiver_email,
            message_id=inbound_mid or f"no-mid-{lead_id}-{datetime.utcnow().timestamp()}",
            reply_subject=subject, reply_body=body[:4000], intent=intent,
        ))
        await session.commit()

    # Load draft for sender/receiver details
    async with AsyncSessionLocal() as session:
        draft = await session.get(FinalizedDraftRecord, lead_id)

    sender_name = (draft.sender_name if draft else None) or sender.display_name or sender.email_address
    sender_role = (draft.sender_role if draft else None) or ""
    sender_company = (draft.sender_company if draft else None) or ""
    receiver_name = (draft.receiver_name if draft else None) or ""
    receiver_role = (draft.receiver_role if draft else None) or ""
    company_name = (draft.company_name if draft else None) or ""
    original_subject = (draft.final_subject if draft else None) or subject

    # Get/create thread and append inbound message
    thread = await get_or_create_thread(user_id, lead_id, receiver_email, company_name)
    await append_message(
        thread_id=thread.id, user_id=user_id, lead_id=lead_id,
        direction="inbound", body=body[:4000], subject=subject,
        message_id=inbound_mid or None, intent=intent,
    )

    # Reload thread with updated turn_count
    async with AsyncSessionLocal() as session:
        thread = await session.get(ConversationThreadRecord, thread.id)

    # Webhooks + lifecycle
    from app.services.webhooks import fire_and_forget
    fire_and_forget("outreach.replied", user_id, {
        "lead_id": lead_id, "company_name": company_name,
        "receiver_email": receiver_email, "intent": intent,
        "thread_id": thread.id, "turn_count": thread.turn_count,
    })
    await _set_lifecycle_status(lead_id, LeadLifecycleStatus.REPLIED, "conversation_agent")

    # ── Intent routing ────────────────────────────────────────────────────────
    if intent == "negative":
        await _set_lifecycle_status(lead_id, LeadLifecycleStatus.LOST, "conversation_agent",
                                    notes="Prospect replied with negative intent.")
        await close_thread(thread.id, "closed_negative")
        return "closed"

    if intent == "positive":
        meeting_data = await extract_meeting_details(body, user_id=user_id)
        is_ready = bool(meeting_data.get("is_ready_to_schedule"))
        status_val = "ready_for_scheduler" if is_ready else "pending_info"

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(MeetingHandoffRecord)
                .where(MeetingHandoffRecord.lead_id == lead_id)
                .where(MeetingHandoffRecord.user_id == user_id)
            )
            handoff = existing.scalar_one_or_none()
            if handoff:
                handoff.contact_name = meeting_data.get("contact_name") or handoff.contact_name
                handoff.contact_role = meeting_data.get("contact_role") or handoff.contact_role
                handoff.meeting_date = meeting_data.get("meeting_date") or handoff.meeting_date
                handoff.meeting_time = meeting_data.get("meeting_time") or handoff.meeting_time
                handoff.timezone = meeting_data.get("timezone") or handoff.timezone
                handoff.preferred_meeting_platform = meeting_data.get("preferred_platform") or handoff.preferred_meeting_platform
                handoff.notes = meeting_data.get("notes") or handoff.notes
                handoff.raw_response = body[:2000]
                handoff.status = status_val
                handoff.updated_at = datetime.utcnow()
                session.add(handoff)
            else:
                session.add(MeetingHandoffRecord(
                    user_id=user_id, lead_id=lead_id, receiver_email=receiver_email,
                    contact_name=meeting_data.get("contact_name"),
                    contact_role=meeting_data.get("contact_role"),
                    meeting_date=meeting_data.get("meeting_date"),
                    meeting_time=meeting_data.get("meeting_time"),
                    timezone=meeting_data.get("timezone"),
                    preferred_meeting_platform=meeting_data.get("preferred_platform"),
                    notes=meeting_data.get("notes"),
                    raw_response=body[:2000], status=status_val,
                ))
            await session.commit()

        if is_ready:
            await _set_lifecycle_status(
                lead_id, LeadLifecycleStatus.MEETING_SCHEDULED, "conversation_agent",
                notes=f"Meeting: {meeting_data.get('meeting_date')} {meeting_data.get('meeting_time')}",
            )
            await update_thread_status(thread.id, "meeting_booked")
        else:
            await update_thread_status(thread.id, "active")

        fire_and_forget("outreach.meeting", user_id, {
            "lead_id": lead_id, "company_name": company_name,
            "receiver_email": receiver_email,
            "meeting_date": meeting_data.get("meeting_date"),
            "meeting_time": meeting_data.get("meeting_time"),
            "is_ready": is_ready,
        })

        if not is_ready:
            await _send_conversational_reply(
                thread=thread, lead_id=lead_id, user_id=user_id,
                sender=sender, smtp_password=smtp_password,
                reply_body=body, original_subject=original_subject,
                sender_name=sender_name, sender_role=sender_role, sender_company=sender_company,
                receiver_name=receiver_name, receiver_role=receiver_role, company_name=company_name,
                in_reply_to_mid=inbound_mid or None,
            )
            return "auto_replied"
        return "processed"

    # Neutral — generate contextual reply
    await _send_conversational_reply(
        thread=thread, lead_id=lead_id, user_id=user_id,
        sender=sender, smtp_password=smtp_password,
        reply_body=body, original_subject=original_subject,
        sender_name=sender_name, sender_role=sender_role, sender_company=sender_company,
        receiver_name=receiver_name, receiver_role=receiver_role, company_name=company_name,
        in_reply_to_mid=inbound_mid or None,
    )
    return "auto_replied"


# ── Inbox poller ──────────────────────────────────────────────────────────────

async def _process_inbox_replies(
    user_id: str, sender: SenderEmailAccountRecord, smtp_password: str,
) -> dict:
    processed = closed = auto_replied = 0
    if _imap_in_auth_cooldown(user_id):
        return {"processed": 0, "closed": 0, "auto_replied": 0}

    imap_host = sender.imap_host or _imap_host_from_smtp(sender.smtp_host)
    imap_user = sender.imap_username or sender.email_address
    imap_pw = decrypt(sender.imap_password_encrypted) if sender.imap_password_encrypted else smtp_password

    async with AsyncSessionLocal() as session:
        sent_result = await session.execute(
            select(OutreachSentRecord)
            .where(OutreachSentRecord.user_id == user_id)
            .where(OutreachSentRecord.outbound_message_id.isnot(None))
        )
        sent_rows = list(sent_result.scalars().all())

    mid_to_sent: dict[str, OutreachSentRecord] = {
        _canonical_mid(r.outbound_message_id): r
        for r in sent_rows if r.outbound_message_id
    }

    async with AsyncSessionLocal() as session:
        reply_result = await session.execute(
            select(OutreachReplyRecord.message_id).where(OutreachReplyRecord.user_id == user_id)
        )
        seen_reply_ids: set[str] = {r[0] for r in reply_result.all() if r[0]}

    try:
        loop = asyncio.get_event_loop()
        raw_messages = await loop.run_in_executor(
            None,
            lambda: _fetch_imap_messages(
                imap_host, sender.imap_port, imap_user, imap_pw,
                sender.imap_use_ssl, _IMAP_LOOKBACK_DAYS, _IMAP_MAX_MESSAGES,
            ),
        )
    except Exception as e:
        if _imap_auth_error(e):
            _set_imap_auth_cooldown(user_id)
            logger.error("outreach_agent.imap_auth_failed", user_id=user_id, error=str(e)[:200])
        else:
            logger.error("outreach_agent.imap_fetch_failed", user_id=user_id, error=str(e)[:200])
        return {"processed": 0, "closed": 0, "auto_replied": 0}

    semaphore = asyncio.Semaphore(_INBOX_PARALLEL_WORKERS)

    async def _handle_one(raw_msg: bytes) -> None:
        nonlocal processed, closed, auto_replied
        async with semaphore:
            result = await _handle_reply_message(
                raw_msg=raw_msg, user_id=user_id, sender=sender,
                smtp_password=smtp_password, mid_to_sent=mid_to_sent,
                seen_reply_ids=seen_reply_ids,
            )
            if result == "closed":
                closed += 1; processed += 1
            elif result == "auto_replied":
                auto_replied += 1; processed += 1
            elif result == "processed":
                processed += 1

    await asyncio.gather(*[_handle_one(m) for m in raw_messages], return_exceptions=True)
    logger.info("outreach_agent.inbox_processed", user_id=user_id,
                processed=processed, closed=closed, auto_replied=auto_replied)
    return {"processed": processed, "closed": closed, "auto_replied": auto_replied}


# ── Main outreach job ─────────────────────────────────────────────────────────

async def run_outreach_job(user_id: str) -> dict:
    """
    Execute one outreach job cycle for a user.
    1. Poll inbox for replies (conversation manager handles them)
    2. Send initial emails and follow-ups for approved drafts
    """
    from app.services.settings import get_settings
    user_settings = await get_settings(user_id)
    outreach_cfg = user_settings.outreach

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

    reply_summary: dict = {"processed": 0, "closed": 0, "auto_replied": 0}
    if outreach_cfg.reply_check_enabled:
        reply_summary = await _process_inbox_replies(user_id, sender, smtp_password)

    if not _in_send_window(outreach_cfg.send_window_start, outreach_cfg.send_window_end):
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "outside_send_window", "replies": reply_summary}

    sent_today = await _get_sent_today(user_id, sender.email_address)
    remaining = min(sender.daily_limit, outreach_cfg.daily_send_limit) - sent_today
    if remaining <= 0:
        return {"sent": 0, "skipped": 0, "failed": 0, "reason": "daily_limit_reached", "replies": reply_summary}

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

    from app.services.sandbox_outreach import SandboxConfigError, resolve_smtp_receiver, is_sandbox_pipeline_run

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
                user_id, draft.lead_id, natural_receiver, sandbox_pipeline=sandbox_pipeline,
            )
        except SandboxConfigError as err:
            logger.warning("outreach_agent.sandbox_resolve_skipped", lead_id=draft.lead_id, error=str(err))
            skipped += 1
            continue

        async with AsyncSessionLocal() as session:
            lifecycle = await session.get(LeadLifecycleRecord, draft.lead_id)
        if lifecycle and lifecycle.current_status in {
            LeadLifecycleStatus.REPLIED.value, LeadLifecycleStatus.MEETING_SCHEDULED.value,
            LeadLifecycleStatus.WON.value, LeadLifecycleStatus.LOST.value, LeadLifecycleStatus.ARCHIVED.value,
        }:
            skipped += 1
            continue

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
            reply_result = await session.execute(
                select(OutreachReplyRecord)
                .where(OutreachReplyRecord.user_id == user_id)
                .where(OutreachReplyRecord.lead_id == draft.lead_id)
                .where(OutreachReplyRecord.receiver_email == receiver_email)
            )
            reply_rows = list(reply_result.scalars().all())

        has_reply = len(reply_rows) > 0
        followup_count = sum(1 for r in sent_rows if r.campaign_stage == "followup")
        has_initial = any(r.campaign_stage == "initial" for r in sent_rows)
        last_sent = sent_rows[0] if sent_rows else None

        should_send = False
        subject = draft.final_subject
        body = draft.final_body
        stage = "initial"
        in_reply_to_mid: str | None = None
        references: str | None = None

        if not has_initial:
            should_send = True
        elif outreach_cfg.followup_enabled and not has_reply:
            max_attempts = outreach_cfg.followup_max_attempts
            if followup_count >= max_attempts:
                initial_send = next((r for r in sent_rows if r.campaign_stage == "initial"), None)
                if initial_send:
                    elapsed_since_initial = datetime.utcnow() - initial_send.sent_at
                    if elapsed_since_initial >= timedelta(days=7):
                        await _set_lifecycle_status(
                            draft.lead_id, LeadLifecycleStatus.LOST, "followup_agent",
                            notes=f"No reply after {followup_count} follow-ups over 7+ days.",
                        )
                        skipped += 1
                        continue
            if last_sent:
                elapsed = datetime.utcnow() - last_sent.sent_at
                if elapsed >= timedelta(hours=outreach_cfg.followup_interval_hours):
                    if followup_count < max_attempts:
                        should_send = True
                        stage = "followup"
                        subject = _build_followup_subject(draft.final_subject, followup_count + 1)
                        body = _build_followup_body(draft, followup_count + 1)
                        initial_send = next((r for r in sent_rows if r.campaign_stage == "initial"), None)
                        if initial_send and initial_send.outbound_message_id:
                            in_reply_to_mid = initial_send.outbound_message_id.strip()
                            refs_chain = [in_reply_to_mid]
                            for fo in [r for r in sent_rows if r.campaign_stage == "followup"]:
                                if fo.outbound_message_id and fo.outbound_message_id not in refs_chain:
                                    refs_chain.append(fo.outbound_message_id.strip())
                            references = " ".join(f"<{_canonical_mid(m)}>" for m in refs_chain if m)

        if not should_send:
            skipped += 1
            continue

        subject, body = clean_outreach_copy(subject, body, for_send=True)

        # Log initial send to conversation thread
        if stage == "initial":
            thread = await get_or_create_thread(
                user_id, draft.lead_id, receiver_email, draft.company_name,
            )

        try:
            outbound_mid = await _send_email_async(
                smtp_host=sender.smtp_host, smtp_port=sender.smtp_port,
                smtp_username=sender.smtp_username, smtp_password=smtp_password,
                use_tls=sender.use_tls,
                from_email=sender.email_address,
                from_name=sender.display_name or sender.email_address,
                to_email=receiver_email, subject=subject, body=body,
                in_reply_to=in_reply_to_mid, references=references,
            )
            await _log_sent(user_id, draft.lead_id, sender.email_address, receiver_email,
                            subject, campaign_stage=stage, outbound_message_id=outbound_mid)
            await _mark_contacted(draft.lead_id, user_id)

            # Append to conversation thread
            if stage == "initial":
                await append_message(
                    thread_id=thread.id, user_id=user_id, lead_id=draft.lead_id,
                    direction="outbound", body=body, subject=subject, message_id=outbound_mid,
                )

            sent += 1
            logger.info("outreach_agent.sent", lead_id=draft.lead_id, to=receiver_email, stage=stage)

            from app.services.webhooks import fire_and_forget
            fire_and_forget("outreach.sent", user_id, {
                "lead_id": draft.lead_id, "company_name": draft.company_name,
                "receiver_email": receiver_email, "subject": subject,
                "campaign_stage": stage,
                "followup_number": followup_count + 1 if stage == "followup" else 0,
                "sender_email": sender.email_address,
            })
        except Exception as e:
            await _log_sent(user_id, draft.lead_id, sender.email_address, receiver_email,
                            subject, status="failed", error=str(e)[:500], campaign_stage=stage)
            failed += 1
            logger.error("outreach_agent.send_failed", lead_id=draft.lead_id, error=str(e)[:200])

    logger.info("outreach_agent.cycle_complete", user_id=user_id,
                sent=sent, skipped=skipped, failed=failed,
                replies_processed=reply_summary["processed"])
    return {"sent": sent, "skipped": skipped, "failed": failed, "replies": reply_summary}


# ── Public alias used by leads.py inbox polling ───────────────────────────────

async def run_followup_inbox_only(user_id: str) -> dict:
    """
    Public entry point for inbox-only polling (no outbound sends).
    Called by the continuous pipeline loop to check replies while discovery runs.
    """
    from app.storage.models import SenderEmailAccountRecord
    from sqlmodel import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == user_id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        sender = result.scalar_one_or_none()

    if not sender:
        return {"processed": 0, "closed": 0, "auto_replied": 0, "reason": "no_sender_account"}

    smtp_password = decrypt(sender.smtp_password_encrypted)
    return await _process_inbox_replies(user_id, sender, smtp_password)
