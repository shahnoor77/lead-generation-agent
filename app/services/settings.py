"""
User Settings Service — load, save, and apply settings to pipeline.
Handles all 5 settings groups: lead_discovery, icp, sender, outreach, ai_agent.
Sender credentials are stored in SenderEmailAccountRecord (encrypted), not UserSettingsRecord.
"""

from __future__ import annotations
import json
from datetime import datetime

from app.storage.database import AsyncSessionLocal
from app.storage.models import UserSettingsRecord
from app.schemas.settings import (
    UserSettingsResponse, UserSettingsRequest,
    LeadDiscoverySettings, ICPSettings, ICPScoringWeights,
    SenderSettings, OutreachSettings, AIAgentSettings,
)
from app.core.logging import get_logger
from app.core.config import settings as app_settings

logger = get_logger(__name__)


async def get_settings(user_id: str) -> UserSettingsResponse:
    async with AsyncSessionLocal() as session:
        rec = await session.get(UserSettingsRecord, user_id)

    sender = await _load_sender_settings(user_id)

    if rec is None:
        return UserSettingsResponse(
            user_id=user_id,
            lead_discovery=LeadDiscoverySettings(),
            icp=ICPSettings(),
            sender=sender,
            outreach=OutreachSettings(),
            ai_agent=AIAgentSettings(),
            sandbox_outreach_available=app_settings.sandbox_outreach_enabled,
        )

    return _to_response(rec, sender=sender)


async def save_settings(user_id: str, req: UserSettingsRequest) -> UserSettingsResponse:
    async with AsyncSessionLocal() as session:
        rec = await session.get(UserSettingsRecord, user_id)
        if rec is None:
            rec = UserSettingsRecord(user_id=user_id)

        if req.lead_discovery:
            ld = req.lead_discovery
            rec.discovery_industries = json.dumps(ld.industries)
            rec.discovery_location = ld.location
            rec.discovery_country = ld.country
            rec.discovery_area = ld.area
            rec.discovery_domain = ld.domain
            rec.discovery_our_services = json.dumps(ld.our_services)
            rec.discovery_pain_points = json.dumps(ld.pain_points)
            rec.discovery_value_proposition = ld.value_proposition
            rec.discovery_excluded_categories = json.dumps(ld.excluded_categories)
            rec.discovery_language_preference = ld.language_preference
            rec.discovery_notes = ld.notes

        if req.icp:
            rec.icp_decision_maker_titles = json.dumps(req.icp.decision_maker_titles)
            rec.icp_target_industries = json.dumps(req.icp.target_industries)
            rec.icp_ownership_types = json.dumps(req.icp.ownership_types)
            rec.icp_revenue_min = req.icp.revenue_min
            rec.icp_revenue_max = req.icp.revenue_max
            rec.icp_growth_stage = req.icp.growth_stage
            rec.icp_primary_geography = req.icp.primary_geography
            rec.icp_min_fit_score = req.icp.min_fit_score
            rec.icp_require_website = req.icp.require_website
            rec.icp_require_contact = req.icp.require_contact
            rec.icp_scoring_weights = json.dumps(req.icp.scoring_weights.model_dump())

        if req.sender:
            await _save_sender_settings(user_id, req.sender)

        if req.outreach:
            rec.outreach_sender_domain = req.outreach.sender_domain
            rec.outreach_daily_send_limit = req.outreach.daily_send_limit
            rec.outreach_send_window_start = req.outreach.send_window_start
            rec.outreach_send_window_end = req.outreach.send_window_end
            rec.outreach_language_default = req.outreach.language_default
            rec.outreach_followup_enabled = req.outreach.followup_enabled
            rec.outreach_reply_check_enabled = req.outreach.reply_check_enabled
            rec.outreach_followup_max_attempts = req.outreach.followup_max_attempts
            rec.outreach_followup_interval_hours = req.outreach.followup_interval_hours

        if req.ai_agent:
            rec.ai_model = req.ai_agent.model
            rec.ai_agent_mode = req.ai_agent.agent_mode
            rec.ai_email_tone = req.ai_agent.email_tone
            rec.ai_hypothesis_depth = req.ai_agent.hypothesis_depth
            rec.ai_summary_depth = req.ai_agent.summary_depth

        rec.updated_at = datetime.utcnow()
        session.add(rec)
        await session.commit()
        await session.refresh(rec)

    sender = await _load_sender_settings(user_id)
    logger.info("settings.saved", user_id=user_id)
    return _to_response(rec, sender=sender, sandbox_available=app_settings.sandbox_outreach_enabled)


async def _load_sender_settings(user_id: str) -> SenderSettings:
    """Load sender account as SenderSettings (no raw passwords)."""
    from sqlmodel import select
    from app.storage.models import SenderEmailAccountRecord
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SenderEmailAccountRecord)
            .where(SenderEmailAccountRecord.user_id == user_id)
            .where(SenderEmailAccountRecord.is_active == True)
            .limit(1)
        )
        acc = result.scalar_one_or_none()

    if not acc:
        return SenderSettings(configured=False)

    return SenderSettings(
        configured=True,
        email_address=acc.email_address,
        display_name=acc.display_name or None,
        smtp_host=acc.smtp_host,
        smtp_port=acc.smtp_port,
        smtp_username=acc.smtp_username,
        smtp_password=None,  # never return raw password
        smtp_password_configured=bool(acc.smtp_password_encrypted),
        use_tls=acc.use_tls,
        daily_limit=acc.daily_limit,
        imap_host=acc.imap_host,
        imap_port=acc.imap_port,
        imap_username=acc.imap_username,
        imap_password=None,
        imap_password_configured=bool(acc.imap_password_encrypted),
        imap_use_ssl=acc.imap_use_ssl,
    )


async def _save_sender_settings(user_id: str, sender: SenderSettings) -> None:
    """Save sender credentials via the outreach account upsert logic."""
    if not sender.email_address or not sender.smtp_host or not sender.smtp_username:
        return  # incomplete — skip silently

    from app.api.routes.outreach_agent import (
        PersistSenderAccountRequest, persist_user_sender_account,
    )
    body = PersistSenderAccountRequest(
        email_address=sender.email_address,
        display_name=sender.display_name or "",
        smtp_host=sender.smtp_host,
        smtp_port=sender.smtp_port,
        smtp_username=sender.smtp_username,
        smtp_password=sender.smtp_password or None,
        use_tls=sender.use_tls,
        daily_limit=sender.daily_limit,
        imap_host=sender.imap_host or None,
        imap_port=sender.imap_port,
        imap_username=sender.imap_username or None,
        imap_password=sender.imap_password or None,
        imap_use_ssl=sender.imap_use_ssl,
    )
    try:
        await persist_user_sender_account(user_id, body)
    except Exception as e:
        logger.warning("settings.sender_save_failed", user_id=user_id, error=str(e)[:200])


def _to_response(
    rec: UserSettingsRecord,
    *,
    sender: SenderSettings | None = None,
    sandbox_available: bool = True,
) -> UserSettingsResponse:
    return UserSettingsResponse(
        user_id=rec.user_id,
        updated_at=rec.updated_at.isoformat() if rec.updated_at else None,
        sandbox_outreach_available=sandbox_available,
        lead_discovery=LeadDiscoverySettings(
            industries=json.loads(getattr(rec, "discovery_industries", '["manufacturing"]')),
            location=getattr(rec, "discovery_location", "Saudi Arabia") or "Saudi Arabia",
            country=getattr(rec, "discovery_country", None),
            area=getattr(rec, "discovery_area", None),
            domain=getattr(rec, "discovery_domain", None),
            our_services=json.loads(getattr(rec, "discovery_our_services", "[]")),
            pain_points=json.loads(getattr(rec, "discovery_pain_points", "[]")),
            value_proposition=getattr(rec, "discovery_value_proposition", None),
            excluded_categories=json.loads(getattr(rec, "discovery_excluded_categories", "[]")),
            language_preference=getattr(rec, "discovery_language_preference", "EN") or "EN",
            notes=getattr(rec, "discovery_notes", None),
        ),
        icp=ICPSettings(
            decision_maker_titles=json.loads(rec.icp_decision_maker_titles),
            target_industries=json.loads(rec.icp_target_industries),
            ownership_types=json.loads(rec.icp_ownership_types),
            revenue_min=rec.icp_revenue_min,
            revenue_max=rec.icp_revenue_max,
            growth_stage=rec.icp_growth_stage,
            primary_geography=rec.icp_primary_geography,
            min_fit_score=rec.icp_min_fit_score,
            require_website=rec.icp_require_website,
            require_contact=rec.icp_require_contact,
            scoring_weights=ICPScoringWeights(**json.loads(rec.icp_scoring_weights)),
        ),
        sender=sender or SenderSettings(configured=False),
        outreach=OutreachSettings(
            sender_domain=rec.outreach_sender_domain,
            daily_send_limit=rec.outreach_daily_send_limit,
            send_window_start=rec.outreach_send_window_start,
            send_window_end=rec.outreach_send_window_end,
            language_default=rec.outreach_language_default,
            followup_enabled=rec.outreach_followup_enabled,
            reply_check_enabled=rec.outreach_reply_check_enabled,
            followup_max_attempts=rec.outreach_followup_max_attempts,
            followup_interval_hours=rec.outreach_followup_interval_hours,
        ),
        ai_agent=AIAgentSettings(
            model=rec.ai_model,
            agent_mode=rec.ai_agent_mode,
            email_tone=rec.ai_email_tone,
            hypothesis_depth=rec.ai_hypothesis_depth,
            summary_depth=rec.ai_summary_depth,
        ),
    )
