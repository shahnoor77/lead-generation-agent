"""FastAPI dependencies for auth."""
from fastapi import Depends
from app.services.auth import oauth2_scheme, decode_token, get_user_by_id, TokenData
from app.storage.models import UserRecord
from fastapi import HTTPException


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserRecord:
    data = decode_token(token)
    user = await get_user_by_id(data.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
