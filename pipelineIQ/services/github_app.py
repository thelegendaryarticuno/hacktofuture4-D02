from __future__ import annotations

import hashlib
import io
import hmac
import time
import zipfile
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


async def download_workflow_logs(
    installation_id: int,
    repository_full_name: str,
    run_id: int,
) -> str:
    installation_token = await get_installation_access_token(installation_id)
    owner, repo = repository_full_name.split("/", 1)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            headers={
                "Authorization": f"Bearer {installation_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=60.0,
        )
        response.raise_for_status()

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    chunks: list[str] = []
    for name in archive.namelist():
        with archive.open(name) as handle:
            content = handle.read().decode("utf-8", errors="replace")
            chunks.append(f"===== {name} =====\n{content}")
    return "\n\n".join(chunks)


async def fetch_compare_diff(
    installation_id: int,
    repository_full_name: str,
    base_sha: str | None,
    head_sha: str | None,
) -> str:
    if not base_sha or not head_sha:
        return "Git diff unavailable: missing base or head SHA."

    installation_token = await get_installation_access_token(installation_id)
    owner, repo = repository_full_name.split("/", 1)
    compare = await _github_request(
        "GET",
        f"/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}",
        token=installation_token,
    )

    files = compare.get("files") or []
    if not files:
        return "No file changes found between base and head."

    chunks: list[str] = []
    for file_item in files[:20]:
        filename = file_item.get("filename", "unknown")
        status = file_item.get("status", "modified")
        additions = file_item.get("additions", 0)
        deletions = file_item.get("deletions", 0)
        patch = (file_item.get("patch") or "").strip()
        if len(patch) > 2000:
            patch = patch[:2000] + "\n...truncated..."

        chunks.append(
            f"File: {filename}\n"
            f"Status: {status} (+{additions}/-{deletions})\n"
            f"Patch:\n{patch or 'Patch unavailable.'}"
        )

    return "\n\n".join(chunks)


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        settings.GITHUB_APP_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
