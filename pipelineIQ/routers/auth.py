from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse

from auth.cookies import clear_session_cookie, set_session_cookie
from auth.dependencies import get_current_user
from auth.jwt import create_access_token
from config import settings
from models.user import GitHubOrganization, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_ORGS_URL = "https://api.github.com/user/orgs"


@router.get("/github")
async def github_login():
    params = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "scope": settings.GITHUB_OAUTH_SCOPES,
        }
    )
    return RedirectResponse(url=f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/github/callback")
async def github_callback(code: str = Query(...), response: Response = None):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}?error=oauth_failed")

    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        gh_user = user_resp.json()
        orgs_resp = await client.get(
            GITHUB_USER_ORGS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        gh_orgs = orgs_resp.json() if orgs_resp.status_code == 200 else []

    organizations = [
        GitHubOrganization(
            id=org["id"],
            login=org["login"],
            avatar_url=org.get("avatar_url"),
            description=org.get("description"),
            url=org.get("url"),
        )
        for org in gh_orgs
    ]

    user = await User.find_one(User.github_id == gh_user["id"])
    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            github_id=gh_user["id"],
            username=gh_user["login"],
            display_name=gh_user.get("name"),
            email=gh_user.get("email"),
            avatar_url=gh_user.get("avatar_url"),
            github_access_token=access_token,
            organizations=organizations,
            last_login=now,
            created_at=now,
        )
        await user.insert()
    else:
        user.github_access_token = access_token
        user.last_login = now
        user.display_name = gh_user.get("name") or user.display_name
        user.email = gh_user.get("email") or user.email
        user.avatar_url = gh_user.get("avatar_url") or user.avatar_url
        user.organizations = organizations
        await user.save()

    jwt_token = create_access_token(str(user.id))
    redirect = RedirectResponse(
        url=f"{settings.FRONTEND_URL}/dashboard", status_code=302
    )
    set_session_cookie(redirect, jwt_token)
    return redirect


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "github_id": user.github_id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "organizations": [
            {
                "id": org.id,
                "login": org.login,
                "avatar_url": org.avatar_url,
                "description": org.description,
                "url": org.url,
            }
            for org in user.organizations
        ],
        "last_login": user.last_login.isoformat(),
        "created_at": user.created_at.isoformat(),
    }


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"detail": "Logged out"}
