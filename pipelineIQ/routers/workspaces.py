from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from models.pipeline_run import PipelineRun
from models.user import User
from models.workspace import RiskProfile, Workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])



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


def serialize_pipeline_run(run: PipelineRun) -> dict:
    return {
        "id": str(run.id),
        "repository_full_name": run.repository_full_name,
        "event_type": run.event_type,
        "action": run.action,
        "run_id": run.run_id,
        "workflow_name": run.workflow_name,
        "workflow_url": run.workflow_url,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "triggered_by": run.triggered_by,
        "conclusion": run.conclusion,
        "health_status": run.health_status,
        "kafka_status": run.kafka_status,
        "monitor_status": run.monitor_status,
        "diagnosis_status": run.diagnosis_status,
        "monitor_summary": run.monitor_summary,
        "monitor_logs_excerpt": run.monitor_logs_excerpt,
        "diagnosis_report": run.diagnosis_report,
        "diagnosis_error": run.diagnosis_error,
        "error_summary": run.error_summary,
        "diagnosis_provider": run.diagnosis_provider,
        "diagnosis_model": run.diagnosis_model,
        "monitor_provider": run.monitor_provider,
        "monitor_model": run.monitor_model,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }



@router.get("")
async def list_workspaces(user: User = Depends(get_current_user)):
    workspaces = await Workspace.find(Workspace.owner_id == user.id).to_list()
    return [serialize_workspace(ws) for ws in workspaces]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate, user: User = Depends(get_current_user)
):
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
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return serialize_workspace(ws)


@router.get("/{workspace_id}/repository-dashboard")
async def get_repository_dashboard(
    workspace_id: str, user: User = Depends(get_current_user)
):
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not ws.github_installation_id or not ws.github_repo_full_name:
        return {
            "workspace": serialize_workspace(ws),
            "health": {
                "status": "unknown",
                "latest_conclusion": None,
                "last_event_at": None,
                "healthy_count": 0,
                "degraded_count": 0,
                "failing_count": 0,
                "total_events": 0,
            },
            "monitor_logs": [],
            "errors": [],
            "diagnosis_reports": [],
        }

    runs = (
        await PipelineRun.find(
            PipelineRun.workspace_id == ws.id,
            PipelineRun.repository_full_name == ws.github_repo_full_name
        )
        .sort(-PipelineRun.updated_at)
        .limit(50)
        .to_list()
    )

    failing_runs = [run for run in runs if run.health_status == "failing"]
    degraded_runs = [run for run in runs if run.health_status == "degraded"]
    healthy_runs = [run for run in runs if run.health_status == "healthy"]
    diagnosis_reports = [
        run for run in runs if run.diagnosis_status == "completed" and run.diagnosis_report
    ]

    latest_run = runs[0] if runs else None

    return {
        "workspace": serialize_workspace(ws),
        "health": {
            "status": latest_run.health_status if latest_run else "unknown",
            "latest_conclusion": latest_run.conclusion if latest_run else None,
            "last_event_at": latest_run.updated_at.isoformat() if latest_run else None,
            "healthy_count": len(healthy_runs),
            "degraded_count": len(degraded_runs),
            "failing_count": len(failing_runs),
            "total_events": len(runs),
        },
        "monitor_logs": [serialize_pipeline_run(run) for run in runs],
        "errors": [serialize_pipeline_run(run) for run in failing_runs],
        "diagnosis_reports": [serialize_pipeline_run(run) for run in diagnosis_reports],
    }


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    user: User = Depends(get_current_user),
):
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
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await ws.delete()
