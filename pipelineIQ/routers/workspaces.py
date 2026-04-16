"""
Workspace CRUD routes.
"""

from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from models.user import User
from models.workspace import RiskProfile, Workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ── Request / Response schemas ─────────────────────────────────────
class RiskProfilePayload(BaseModel):
    production_branch: str = "main"
    require_approval_above: int = Field(60, ge=0, le=100)
    auto_fix_below: int = Field(30, ge=0, le=100)


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    risk_profile: RiskProfilePayload = Field(default_factory=RiskProfilePayload)


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    risk_profile: RiskProfilePayload | None = None


def serialize_workspace(ws: Workspace) -> dict:
    connected = bool(ws.github_installation_id and ws.github_repo_full_name)
    return {
        "id": str(ws.id),
        "name": ws.name,
        "description": ws.description,
        "github_installation_id": ws.github_installation_id,
        "github_repository_id": ws.github_repository_id,
        "github_repo_full_name": ws.github_repo_full_name,
        "github_default_branch": ws.github_default_branch,
        "github_repo_private": ws.github_repo_private,
        "github_repo_html_url": ws.github_repo_html_url,
        "github_account_login": ws.github_account_login,
        "github_account_type": ws.github_account_type,
        "connected": connected,
        "risk_profile": {
            "production_branch": ws.risk_profile.production_branch,
            "require_approval_above": ws.risk_profile.require_approval_above,
            "auto_fix_below": ws.risk_profile.auto_fix_below,
        },
        "connected_at": ws.connected_at.isoformat() if ws.connected_at else None,
        "last_webhook_event_at": (
            ws.last_webhook_event_at.isoformat() if ws.last_webhook_event_at else None
        ),
        "created_at": ws.created_at.isoformat(),
        "updated_at": ws.updated_at.isoformat(),
    }


# ── Routes ─────────────────────────────────────────────────────────
@router.get("")
async def list_workspaces(user: User = Depends(get_current_user)):
    """Return all workspaces owned by the current user."""
    workspaces = await Workspace.find(Workspace.owner_id == user.id).to_list()
    return [serialize_workspace(ws) for ws in workspaces]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate, user: User = Depends(get_current_user)
):
    """Create a new workspace for the current user."""
    now = datetime.now(timezone.utc)
    ws = Workspace(
        name=body.name,
        description=body.description,
        owner_id=user.id,
        risk_profile=RiskProfile(**body.risk_profile.model_dump()),
        created_at=now,
        updated_at=now,
    )
    await ws.insert()
    return serialize_workspace(ws)


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str, user: User = Depends(get_current_user)
):
    """Get a single workspace with its connected repositories."""
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return serialize_workspace(ws)


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    user: User = Depends(get_current_user),
):
    """Update a workspace's name or description."""
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description
    if body.risk_profile is not None:
        ws.risk_profile = RiskProfile(**body.risk_profile.model_dump())
    ws.updated_at = datetime.now(timezone.utc)
    await ws.save()
    return serialize_workspace(ws)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str, user: User = Depends(get_current_user)
):
    """Delete a workspace and all its connected repositories."""
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await ws.delete()
