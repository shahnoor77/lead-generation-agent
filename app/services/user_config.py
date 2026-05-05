"""
User Lead Config Service

Saves and loads the operator's last-used lead generation configuration.
Called automatically when a run starts (save) and when the form loads (load).
"""

from __future__ import annotations
import json
from datetime import datetime

from app.storage.database import AsyncSessionLocal
from app.storage.models import UserLeadConfigRecord
from app.schemas import BusinessContext, OutreachLanguage
from app.core.logging import get_logger
from sqlmodel import select

logger = get_logger(__name__)


async def save_user_config(user_id: int, context: BusinessContext) -> None:
    """Persist the user's current lead generation config."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserLeadConfigRecord).where(UserLeadConfigRecord.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        now = datetime.utcnow()
        if existing:
            existing.industries = json.dumps(context.industries)
            existing.location = context.location
            existing.country = context.country
            existing.domain = context.domain
            existing.area = context.area
            existing.excluded_categories = json.dumps(context.excluded_categories)
            existing.our_services = json.dumps(context.our_services)
            existing.target_pain_patterns = json.dumps(context.target_pain_patterns)
            existing.pain_points = json.dumps(context.pain_points)
            existing.value_proposition = context.value_proposition
            existing.language_preference = context.language_preference.value
            existing.notes = context.notes
            existing.continuous = context.continuous
            existing.continuous_interval_minutes = context.continuous_interval_minutes
            existing.updated_at = now
            session.add(existing)
        else:
            session.add(UserLeadConfigRecord(
                user_id=user_id,
                industries=json.dumps(context.industries),
                location=context.location,
                country=context.country,
                domain=context.domain,
                area=context.area,
                excluded_categories=json.dumps(context.excluded_categories),
                our_services=json.dumps(context.our_services),
                target_pain_patterns=json.dumps(context.target_pain_patterns),
                pain_points=json.dumps(context.pain_points),
                value_proposition=context.value_proposition,
                language_preference=context.language_preference.value,
                notes=context.notes,
                continuous=context.continuous,
                continuous_interval_minutes=context.continuous_interval_minutes,
                updated_at=now,
            ))
        await session.commit()
    logger.info("user_config.saved", user_id=user_id)


async def load_user_config(user_id: int) -> dict | None:
    """Load the user's last-used config as a plain dict (for API response)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserLeadConfigRecord).where(UserLeadConfigRecord.user_id == user_id)
        )
        rec = result.scalar_one_or_none()

    if not rec:
        return None

    return {
        "industries": json.loads(rec.industries),
        "location": rec.location,
        "country": rec.country,
        "domain": rec.domain,
        "area": rec.area,
        "excluded_categories": json.loads(rec.excluded_categories),
        "our_services": json.loads(rec.our_services),
        "target_pain_patterns": json.loads(rec.target_pain_patterns),
        "pain_points": json.loads(rec.pain_points),
        "value_proposition": rec.value_proposition,
        "language_preference": rec.language_preference,
        "notes": rec.notes,
        "continuous": rec.continuous,
        "continuous_interval_minutes": rec.continuous_interval_minutes,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }
