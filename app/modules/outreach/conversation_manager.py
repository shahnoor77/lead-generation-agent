"""
Conversation Manager — per-lead conversational memory and LLM reply generation.

Flow:
  1. get_or_create_thread()  — one thread per (user_id, lead_id, receiver_email)
  2. append_message()        — log every inbound/outbound message
  3. build_llm_context()     — full history if turns <= SUMMARY_THRESHOLD,
                               else summary + last RECENT_TURNS_KEPT turns
  4. generate_reply()        — LLM generates reply, validated before return
  5. maybe_summarize()       — triggered when turn_count > SUMMARY_THRESHOLD,
                               compresses old turns into rolling summary

Summarization strategy:
  - Summarize when turn_count > 6
  - Keep last 2 turns verbatim always
  - Regenerate summary every 3 turns after threshold
  - Summary stored in ConversationThreadRecord.summary
"""

from __future__ import annotations
import json
from datetime import datetime

from sqlmodel import select
from app.storage.database import AsyncSessionLocal
from app.storage.models import (
    ConversationThreadRecord,
    ConversationMessageRecord,
    MeetingHandoffRecord,
)
from app.utils.llm_client import llm_chat
from app.utils.prompt_loader import load_prompt
from app.modules.outreach.email_sanitize import clean_outreach_copy
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
SUMMARY_THRESHOLD = 6       # summarize when turn_count exceeds this
RECENT_TURNS_KEPT = 2       # always keep this many recent turns verbatim
SUMMARIZE_EVERY_N = 3       # re-summarize every N turns after threshold


# ── Thread management ─────────────────────────────────────────────────────────

async def get_or_create_thread(
    user_id: str,
    lead_id: str,
    receiver_email: str,
    company_name: str = "",
) -> ConversationThreadRecord:
    """Return existing thread or create a new one."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConversationThreadRecord)
            .where(ConversationThreadRecord.user_id == user_id)
            .where(ConversationThreadRecord.lead_id == lead_id)
            .where(ConversationThreadRecord.receiver_email == receiver_email)
        )
        thread = result.scalar_one_or_none()
        if thread:
            return thread

        thread = ConversationThreadRecord(
            user_id=user_id,
            lead_id=lead_id,
            receiver_email=receiver_email,
            company_name=company_name,
            turn_count=0,
            status="active",
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        logger.info("conversation.thread_created",
                    thread_id=thread.id, lead_id=lead_id, user_id=user_id)
        return thread


async def append_message(
    thread_id: str,
    user_id: str,
    lead_id: str,
    direction: str,          # "outbound" | "inbound"
    body: str,
    subject: str = "",
    message_id: str | None = None,
    intent: str | None = None,
) -> ConversationMessageRecord:
    """Append a message to the thread and increment turn_count."""
    async with AsyncSessionLocal() as session:
        msg = ConversationMessageRecord(
            thread_id=thread_id,
            user_id=user_id,
            lead_id=lead_id,
            direction=direction,
            message_id=message_id,
            subject=subject,
            body=body,
            intent=intent,
            sent_at=datetime.utcnow(),
        )
        session.add(msg)

        # Increment turn count on thread
        thread = await session.get(ConversationThreadRecord, thread_id)
        if thread:
            thread.turn_count += 1
            thread.updated_at = datetime.utcnow()
            session.add(thread)

        await session.commit()
        await session.refresh(msg)
        return msg


async def _load_thread_messages(thread_id: str) -> list[ConversationMessageRecord]:
    """Load all messages for a thread ordered by sent_at."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.thread_id == thread_id)
            .order_by(ConversationMessageRecord.sent_at.asc())
        )
        return list(result.scalars().all())


# ── Context builder ───────────────────────────────────────────────────────────

def _format_message(msg: ConversationMessageRecord) -> str:
    direction_label = "US" if msg.direction == "outbound" else "PROSPECT"
    ts = msg.sent_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"[{direction_label} — {ts}]\n{msg.body.strip()}"


async def build_llm_context(thread: ConversationThreadRecord) -> str:
    """
    Build the conversation context string to inject into the LLM prompt.
    - turns <= SUMMARY_THRESHOLD: full history
    - turns > SUMMARY_THRESHOLD: summary + last RECENT_TURNS_KEPT turns
    """
    messages = await _load_thread_messages(thread.id)

    if thread.turn_count <= SUMMARY_THRESHOLD or not thread.summary:
        # Full history
        parts = [_format_message(m) for m in messages]
        return "\n\n---\n\n".join(parts)

    # Summarized history + recent turns
    recent = messages[-RECENT_TURNS_KEPT:]
    recent_text = "\n\n---\n\n".join(_format_message(m) for m in recent)

    return (
        f"[CONVERSATION SUMMARY — turns 1 to {thread.summary_turn_count}]\n"
        f"{thread.summary}\n\n"
        f"[RECENT MESSAGES]\n\n"
        f"{recent_text}"
    )


# ── Summarizer ────────────────────────────────────────────────────────────────

async def maybe_summarize(
    thread: ConversationThreadRecord,
    sender_name: str,
    sender_company: str,
    receiver_name: str,
    user_id: str | None = None,
) -> None:
    """
    Trigger summarization if turn_count > SUMMARY_THRESHOLD and
    it's been SUMMARIZE_EVERY_N turns since last summary.
    """
    if thread.turn_count <= SUMMARY_THRESHOLD:
        return

    turns_since_summary = thread.turn_count - thread.summary_turn_count
    if turns_since_summary < SUMMARIZE_EVERY_N:
        return

    messages = await _load_thread_messages(thread.id)
    # Summarize all but the last RECENT_TURNS_KEPT messages
    to_summarize = messages[:-RECENT_TURNS_KEPT] if len(messages) > RECENT_TURNS_KEPT else messages

    if not to_summarize:
        return

    turns_text = "\n\n---\n\n".join(_format_message(m) for m in to_summarize)

    prompt = load_prompt("conversation_summarize").format(
        sender_name=sender_name,
        sender_company=sender_company,
        receiver_name=receiver_name,
        company_name=thread.company_name,
        conversation_turns=turns_text,
    )

    try:
        response = await llm_chat(
            messages=[
                {"role": "system", "content": "You are a factual summarizer. Return only the summary text."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.1,
            user_id=user_id,
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            async with AsyncSessionLocal() as session:
                t = await session.get(ConversationThreadRecord, thread.id)
                if t:
                    t.summary = summary
                    t.summary_turn_count = thread.turn_count - RECENT_TURNS_KEPT
                    t.updated_at = datetime.utcnow()
                    session.add(t)
                    await session.commit()
            logger.info("conversation.summarized",
                        thread_id=thread.id, turn_count=thread.turn_count)
    except Exception as e:
        logger.warning("conversation.summarize_failed", thread_id=thread.id, error=str(e)[:200])


# ── Reply generator ───────────────────────────────────────────────────────────

async def generate_conversational_reply(
    thread: ConversationThreadRecord,
    latest_reply_body: str,
    original_subject: str,
    sender_name: str,
    sender_role: str,
    sender_company: str,
    receiver_name: str,
    receiver_role: str,
    user_id: str | None = None,
) -> tuple[str, str]:
    """
    Generate a contextual reply using conversation history.
    Returns (subject, body).
    Raises on complete failure — caller should fall back to simple template.
    """
    conversation_context = await build_llm_context(thread)

    prompt = load_prompt("conversation_reply").format(
        sender_name=sender_name,
        sender_role=sender_role or "Sales Representative",
        sender_company=sender_company,
        receiver_name=receiver_name or "there",
        receiver_role=receiver_role or "Decision Maker",
        company_name=thread.company_name,
        conversation_context=conversation_context,
        latest_reply=latest_reply_body.strip(),
        original_subject=original_subject,
    )

    response = await llm_chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a JSON-only responder. Output ONLY valid JSON. "
                    "The email must be professional, under 120 words, and never mention AI or automation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
        temperature=0.3,
        user_id=user_id,
    )

    raw = (response.choices[0].message.content or "{}").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    data = json.loads(raw)
    subject = str(data.get("subject", f"Re: {original_subject}")).strip()[:120]
    body = str(data.get("body", "")).strip()

    if not body:
        raise ValueError("LLM returned empty body")

    # Validate — strip any internal markers
    subject, body = clean_outreach_copy(subject, body, for_send=True)

    # Word count guard
    words = body.split()
    if len(words) > 180:
        body = " ".join(words[:180])

    return subject, body


# ── Meeting detail extractor ──────────────────────────────────────────────────

async def extract_meeting_details(
    reply_body: str,
    user_id: str | None = None,
) -> dict:
    """
    Extract structured meeting details from a positive reply.
    Returns a dict matching MeetingHandoffRecord fields.
    """
    prompt = load_prompt("meeting_extraction").format(reply_body=reply_body.strip())

    try:
        response = await llm_chat(
            messages=[
                {"role": "system", "content": "You are a JSON-only responder. Output ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.0,
            user_id=user_id,
        )
        raw = (response.choices[0].message.content or "{}").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("conversation.meeting_extraction_failed", error=str(e)[:200])
        return {}


# ── Thread status updater ─────────────────────────────────────────────────────

async def close_thread(thread_id: str, status: str) -> None:
    """Close a thread with a terminal status."""
    async with AsyncSessionLocal() as session:
        thread = await session.get(ConversationThreadRecord, thread_id)
        if thread:
            thread.status = status
            thread.updated_at = datetime.utcnow()
            session.add(thread)
            await session.commit()


async def update_thread_status(thread_id: str, status: str) -> None:
    async with AsyncSessionLocal() as session:
        thread = await session.get(ConversationThreadRecord, thread_id)
        if thread:
            thread.status = status
            thread.updated_at = datetime.utcnow()
            session.add(thread)
            await session.commit()
