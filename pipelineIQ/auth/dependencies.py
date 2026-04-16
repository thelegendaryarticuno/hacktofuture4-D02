"""
FastAPI dependencies for authentication / authorisation.
"""

from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from fastapi import Cookie, HTTPException, Response, status
from jose import JWTError

from auth.cookies import set_session_cookie
from auth.jwt import create_access_token, decode_access_token
from models.user import User


async def get_current_user(
    response: Response,
    piq_session: str | None = Cookie(default=None),
) -> User:
    """
    Extract and validate the JWT from the `piq_session` HTTP-only cookie.
    Auto-refreshes the token when less than 3 days remain.
    Returns the authenticated User document.
    """
    if piq_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_access_token(piq_session)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = await User.get(PydanticObjectId(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # --- Token refresh: re-issue if < 3 days remaining ---
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    if exp - datetime.now(timezone.utc) < timedelta(days=3):
        new_token = create_access_token(str(user.id))
        set_session_cookie(response, new_token)

    return user
