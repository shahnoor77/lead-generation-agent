"""
User Settings endpoints.

GET  /api/v1/settings          Get current user's settings
PUT  /api/v1/settings          Save/update settings (partial update supported)
"""

from fastapi import APIRouter, Depends
from app.schemas.settings import UserSettingsRequest, UserSettingsResponse
from app.services.settings import get_settings, save_settings
from app.api.dependencies import get_current_user
from app.storage.models import UserRecord

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=UserSettingsResponse)
async def get_user_settings(
    current_user: UserRecord = Depends(get_current_user),
) -> UserSettingsResponse:
    """Get current user's ICP, outreach, and AI agent settings."""
    return await get_settings(current_user.id)


@router.put("/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> UserSettingsResponse:
    """
    Save user settings. All groups are optional — only provided groups are updated.

    Example (update ICP only):
    {
      "icp": {
        "decision_maker_titles": ["CEO", "COO", "GM"],
        "min_fit_score": 55,
        "require_website": true
      }
    }

    Example (update AI agent only):
    {
      "ai_agent": {
        "email_tone": "executive-direct",
        "hypothesis_depth": "detailed",
        "summary_depth": "detailed"
      }
    }
    """
    return await save_settings(current_user.id, body)
