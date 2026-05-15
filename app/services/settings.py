"""
User Settings Service — load, save, and apply settings to pipeline.
"""

from __future__ import annotations
import json
from datetime import datetime

from app.storage.database import AsyncSessionLocal
from app.storage.models import UserSettingsRecord
from app.schemas.settings import (
    UserSettingsResponse, UserSettingsRequest,
    ICPSettings, OutreachSettings, AIAgentSettings,
)
from app.core.logging import get_logger
from app.core.config import settings as app_settings

logger = get_logger(__name__)


def _defaults() -> UserSettingsRecord:
    return UserSettingsRecord(user_id=0)  # placeholder for defaults


async def get_settings(user_id: int) -> UserSettingsResponse:
    async with AsyncSessionLocal() as session:
        rec = await session.get(UserSettingsRecord, user_id)

    if rec is None:
        # Return defaults without persisting
        return UserSettingsResponse(
            user_id=user_id,
            icp=ICPSettings(),
            outreach=OutreachSettings(),
            ai_agent=AIAgentSettings(),
        )

    return _to_response(rec)


async def save_settings(user_id: int, req: UserSettingsRequest) -> UserSettingsResponse:
    async with AsyncSessionLocal() as session:
        rec = await session.get(UserSettingsRecord, user_id)
        if rec is None:
            rec = UserSettingsRecord(user_id=user_id)

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

    logger.info("settings.saved", user_id=user_id)
    return _to_response(rec, sandbox_available=app_settings.sandbox_outreach_enabled)


def _to_response(rec: UserSettingsRecord, *, sandbox_available: bool = True) -> UserSettingsResponse:
    return UserSettingsResponse(
        user_id=rec.user_id,
        updated_at=rec.updated_at.isoformat() if rec.updated_at else None,
        sandbox_outreach_available=sandbox_available,
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
        ),
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
