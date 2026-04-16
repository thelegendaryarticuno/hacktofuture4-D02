from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError

from auth.dependencies import get_current_user
from models.user import User
from models.webhook_event import WebhookEvent
from models.workspace import Workspace
from services.github_app import (
    create_installation_state,
    decode_installation_state,
    get_installation_details,
    list_installation_repositories,
    verify_webhook_signature,
)
from services.pipeline_runtime import pipeline_runtime, should_process_pipeline_event

from config import settings

router = APIRouter(tags=["github-app"])


@router.get("/api/workspaces/{workspace_id}/github/install")
async def start_github_app_install(
    workspace_id: str,
    user: User = Depends(get_current_user),
):
    workspace = await Workspace.get(PydanticObjectId(workspace_id))
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    state = create_installation_state(str(user.id), workspace_id)
    install_url = f"{settings.github_app_install_url}?state={state}"
    return RedirectResponse(url=install_url, status_code=status.HTTP_302_FOUND)


@router.get("/api/github/installations/callback")
async def github_app_install_callback(
    installation_id: int = Query(...),
    setup_action: str | None = Query(default=None),
    state: str = Query(...),
):
    try:
        install_state = decode_installation_state(state)
    except JWTError:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?installation=invalid_state"
        )

    workspace = await Workspace.get(PydanticObjectId(install_state["workspace_id"]))
    if workspace is None:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?installation=workspace_missing"
        )

    try:
        installation = await get_installation_details(installation_id)
        repositories = await list_installation_repositories(installation_id)
    except Exception:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/workspace/{workspace.id}?installation=github_lookup_failed"
        )

    selected_repo = repositories[0] if repositories else None
    account = installation.get("account") or {}

    workspace.github_installation_id = installation_id
    workspace.github_account_login = account.get("login")
    workspace.github_account_type = account.get("type")
    workspace.connected_at = datetime.now(timezone.utc)
    workspace.updated_at = datetime.now(timezone.utc)

    if selected_repo:
        workspace.github_repository_id = selected_repo.get("id")
        workspace.github_repo_full_name = selected_repo.get("full_name")
        workspace.github_default_branch = selected_repo.get("default_branch", "main")
        workspace.github_repo_private = selected_repo.get("private")
        workspace.github_repo_html_url = selected_repo.get("html_url")

    await workspace.save()

    redirect_url = (
        f"{settings.FRONTEND_URL}/workspace/{workspace.id}"
        f"?installation=success&setup_action={setup_action or 'install'}"
    )
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.delete("/api/workspaces/{workspace_id}/github/installation")
async def disconnect_github_installation(
    workspace_id: str,
    user: User = Depends(get_current_user),
):
    workspace = await Workspace.get(PydanticObjectId(workspace_id))
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    workspace.github_installation_id = None
    workspace.github_repository_id = None
    workspace.github_repo_full_name = None
    workspace.github_default_branch = None
    workspace.github_repo_private = None
    workspace.github_repo_html_url = None
    workspace.github_account_login = None
    workspace.github_account_type = None
    workspace.connected_at = None
    workspace.updated_at = datetime.now(timezone.utc)
    await workspace.save()
    return {"detail": "GitHub App disconnected"}


@router.get("/api/workspaces/{workspace_id}/github/events")
async def list_workspace_events(
    workspace_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
):
    workspace = await Workspace.get(PydanticObjectId(workspace_id))
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not workspace.github_installation_id:
        return []

    events = (
        await WebhookEvent.find(
            WebhookEvent.installation_id == workspace.github_installation_id
        )
        .sort(-WebhookEvent.received_at)
        .limit(limit)
        .to_list()
    )

    return [
        {
            "delivery_id": event.delivery_id,
            "event_type": event.event_type,
            "action": event.action,
            "repository_full_name": event.repository_full_name,
            "received_at": event.received_at.isoformat(),
        }
        for event in events
    ]


@router.post("/api/github/webhooks", status_code=status.HTTP_202_ACCEPTED)
@router.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    installation_id = payload.get("installation", {}).get("id")
    repo_full_name = payload.get("repository", {}).get("full_name")
    action = payload.get("action")

    existing = await WebhookEvent.find_one(WebhookEvent.delivery_id == delivery_id)
    if existing is None:
        await WebhookEvent(
            delivery_id=delivery_id,
            event_type=event_type,
            action=action,
            installation_id=installation_id,
            repository_full_name=repo_full_name,
            payload=payload,
        ).insert()

    workspace = None
    if installation_id is not None:
        workspace = await Workspace.find_one(
            Workspace.github_installation_id == installation_id
        )
        if workspace is not None:
            workspace.last_webhook_event_at = datetime.now(timezone.utc)
            workspace.updated_at = datetime.now(timezone.utc)
            await workspace.save()

    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found for installation")

    if event_type in ("installation", "installation_repositories", "installation_target"):
        return {
            "received": True,
            "event_type": event_type,
            "delivery_id": delivery_id,
            "workspace_id": str(workspace.id),
            "ignored": "This event type is not a CI pipeline event."
        }

    if not should_process_pipeline_event(event_type, payload):
        return {
            "received": True,
            "event_type": event_type,
            "delivery_id": delivery_id,
            "workspace_id": str(workspace.id),
            "ignored": "Only completed workflow_run events are tracked.",
        }

    pipeline_run = await pipeline_runtime.queue_event(
        workspace=workspace,
        event_type=event_type,
        delivery_id=delivery_id,
        payload=payload,
    )

    return {
        "received": True,
        "event_type": event_type,
        "delivery_id": delivery_id,
        "workspace_id": str(workspace.id),
        "repo": repo_full_name or workspace.github_repo_full_name,
        "run_id": pipeline_run.run_id,
        "conclusion": pipeline_run.conclusion,
        "branch": pipeline_run.branch,
        "commit_sha": pipeline_run.commit_sha,
        "triggered_by": pipeline_run.triggered_by,
        "kafka_topic": settings.KAFKA_PIPELINE_EVENTS_TOPIC,
    }
