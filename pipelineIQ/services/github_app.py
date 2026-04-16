"""
GitHub App helpers for installation setup, installation tokens, and webhooks.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx
from jose import JWTError, jwt

from config import settings

GITHUB_API_BASE = "https://api.github.com"


def create_installation_state(user_id: str, workspace_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "type": "github_app_install",
        "iat": now,
        "exp": now + 900,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_installation_state(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
    if payload.get("type") != "github_app_install":
        raise JWTError("Invalid installation state")
    return payload


def create_github_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 540,
        "iss": settings.GITHUB_APP_ID,
    }
    return jwt.encode(
        payload,
        settings.github_app_private_key_pem,
        algorithm="RS256",
    )


async def _github_request(
    method: str,
    path: str,
    *,
    token: str,
    token_type: str = "Bearer",
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            f"{GITHUB_API_BASE}{path}",
            json=json_body,
            headers={
                "Authorization": f"{token_type} {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}


async def get_installation_access_token(installation_id: int) -> str:
    app_jwt = create_github_app_jwt()
    token_response = await _github_request(
        "POST",
        f"/app/installations/{installation_id}/access_tokens",
        token=app_jwt,
    )
    return token_response["token"]


async def get_installation_details(installation_id: int) -> dict[str, Any]:
    app_jwt = create_github_app_jwt()
    return await _github_request(
        "GET",
        f"/app/installations/{installation_id}",
        token=app_jwt,
    )


async def list_installation_repositories(installation_id: int) -> list[dict[str, Any]]:
    installation_token = await get_installation_access_token(installation_id)
    repos_response = await _github_request(
        "GET",
        "/installation/repositories",
        token=installation_token,
    )
    return repos_response.get("repositories", [])


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        settings.GITHUB_APP_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
