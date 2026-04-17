from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from auth.dependencies import get_current_user
from models.autofix_execution import AutoFixExecution
from models.pipeline_run import PipelineRun
from models.user import User
from models.workspace import RiskProfile, Workspace
from services.autofix_service import execute_autofix_policy
from services.risk_classifier import classify_and_store_risk_for_pipeline_run

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])



class RiskProfilePayload(BaseModel):
    production_branch: str = "main"
    require_approval_above: int = Field(60, ge=0, le=100)
    auto_fix_below: int = Field(30, ge=0, le=100)

    @model_validator(mode="after")
    def validate_threshold_order(self):
        if self.auto_fix_below > self.require_approval_above:
            raise ValueError("Auto-fix below must be less than or equal to require approval above.")
        return self


class WorkspaceCreate(BaseModel):
    name: str
    description: str | None = None
    slack_devops_mention: str | None = None
    risk_profile: RiskProfilePayload = Field(default_factory=RiskProfilePayload)


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    slack_devops_mention: str | None = None
    risk_profile: RiskProfilePayload | None = None


def _display_branch(run: PipelineRun) -> str:
    raw_event = run.raw_event or {}
    workflow_run = raw_event.get("workflow_run") or {}
    repository = raw_event.get("repository") or {}
    pull_requests = workflow_run.get("pull_requests") or []
    pull_request = pull_requests[0] if pull_requests else {}

    candidates = [
        run.branch,
        run.diagnosis_report_json.get("branch") if run.diagnosis_report_json else None,
        run.monitor_report_json.get("branch") if run.monitor_report_json else None,
        workflow_run.get("head_branch"),
        ((pull_request.get("head") or {}).get("ref")),
        ((pull_request.get("base") or {}).get("ref")),
        repository.get("default_branch"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "unknown"


def _commit_title(run: PipelineRun) -> str:
    raw_event = run.raw_event or {}
    workflow_run = raw_event.get("workflow_run") or {}
    head_commit = workflow_run.get("head_commit") or {}
    candidates = [
        workflow_run.get("display_title"),
        head_commit.get("message"),
        run.workflow_name,
        run.commit_sha[:7] if run.commit_sha else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().splitlines()[0]
    return "Unknown commit"


def _issue_preview(run: PipelineRun) -> str:
    diagnosis_report = run.diagnosis_report_json or {}
    possible_causes = diagnosis_report.get("possible_causes") or []
    if possible_causes:
        first = possible_causes[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    error_type = diagnosis_report.get("error_type")
    if isinstance(error_type, str) and error_type.strip():
        return error_type.strip()
    if isinstance(run.error_summary, str) and run.error_summary.strip():
        return run.error_summary.strip().splitlines()[0]
    return "No issue summary captured."


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
        "slack_devops_mention": ws.slack_devops_mention,
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
        "commit_title": _commit_title(run),
        "workflow_url": run.workflow_url,
        "workflow_status": run.workflow_status,
        "branch": run.branch,
        "display_branch": _display_branch(run),
        "commit_sha": run.commit_sha,
        "triggered_by": run.triggered_by,
        "conclusion": run.conclusion,
        "health_status": run.health_status,
        "kafka_status": run.kafka_status,
        "monitor_status": run.monitor_status,
        "diagnosis_status": run.diagnosis_status,
        "risk_status": run.risk_status,
        "monitor_summary": run.monitor_summary,
        "monitor_report_json": run.monitor_report_json,
        "monitor_logs_excerpt": run.monitor_logs_excerpt,
        "diagnosis_report": run.diagnosis_report,
        "diagnosis_report_json": run.diagnosis_report_json,
        "issue_preview": _issue_preview(run),
        "diagnosis_error": run.diagnosis_error,
        "risk_score": run.risk_score,
        "risk_band": run.risk_band,
        "risk_report_json": run.risk_report_json,
        "risk_inputs_json": run.risk_inputs_json,
        "risk_error": run.risk_error,
        "risk_provider": run.risk_provider,
        "risk_model": run.risk_model,
        "autofix_status": run.autofix_status,
        "autofix_mode": run.autofix_mode,
        "autofix_report_url": run.autofix_report_url,
        "autofix_pr_url": run.autofix_pr_url,
        "autofix_execution_id": run.autofix_execution_id,
        "autofix_error": run.autofix_error,
        "autofix_feedback_url": run.autofix_feedback_url,
        "autofix_feedback_status": run.autofix_feedback_status,
        "error_summary": run.error_summary,
        "diagnosis_provider": run.diagnosis_provider,
        "diagnosis_model": run.diagnosis_model,
        "monitor_provider": run.monitor_provider,
        "monitor_model": run.monitor_model,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def serialize_autofix_execution(execution: AutoFixExecution, pipeline_run: PipelineRun | None = None) -> dict:
    report = execution.report_json or {}
    return {
        "id": str(execution.id),
        "pipeline_run_id": str(execution.pipeline_run_id),
        "repository_full_name": execution.repository_full_name,
        "target_branch": execution.target_branch,
        "mode": execution.mode,
        "policy_action": execution.policy_action,
        "execution_status": execution.execution_status,
        "report_feedback_status": execution.report_feedback_status,
        "report_feedback_note": execution.report_feedback_note,
        "resolution_feedback_status": execution.resolution_feedback_status,
        "resolution_feedback_url": execution.resolution_feedback_url,
        "reviewer_username": execution.reviewer_username,
        "pr_number": execution.pr_number,
        "pr_url": execution.pr_url,
        "fix_branch": execution.fix_branch,
        "loop_blocked_reason": execution.loop_blocked_reason,
        "risk_score": execution.risk_score,
        "workflow_name": (pipeline_run.workflow_name if pipeline_run else None) or report.get("workflow_name"),
        "branch": (pipeline_run.branch if pipeline_run else None) or report.get("branch"),
        "commit_sha": pipeline_run.commit_sha if pipeline_run else report.get("commit_sha"),
        "fix_summary": report.get("fix_summary") or (execution.proposed_fix_json or {}).get("summary"),
        "possible_fix_steps": report.get("possible_fix_steps") or [],
        "report_url": report.get("report_url"),
        "created_at": execution.created_at.isoformat(),
        "updated_at": execution.updated_at.isoformat(),
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
        slack_devops_mention=body.slack_devops_mention,
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
            "autofix_reports": [],
        }

    runs = (
        await PipelineRun.find(
            PipelineRun.workspace_id == ws.id,
            PipelineRun.repository_full_name == ws.github_repo_full_name,
            PipelineRun.event_type == "workflow_run",
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

    executions = (
        await AutoFixExecution.find(
            AutoFixExecution.workspace_id == ws.id,
            AutoFixExecution.repository_full_name == ws.github_repo_full_name,
        )
        .sort(-AutoFixExecution.updated_at)
        .limit(50)
        .to_list()
    )

    run_by_id = {str(run.id): run for run in runs}
    autofix_reports = [
        serialize_autofix_execution(execution, run_by_id.get(str(execution.pipeline_run_id)))
        for execution in executions
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
        "autofix_reports": autofix_reports,
    }


@router.post("/{workspace_id}/diagnosis/backfill-risk")
async def backfill_workspace_risk_reports(
    workspace_id: str,
    user: User = Depends(get_current_user),
):
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not ws.github_repo_full_name:
        raise HTTPException(status_code=400, detail="No repository connected to this workspace")

    runs = (
        await PipelineRun.find(
            PipelineRun.workspace_id == ws.id,
            PipelineRun.repository_full_name == ws.github_repo_full_name,
            PipelineRun.event_type == "workflow_run",
            PipelineRun.diagnosis_status == "completed",
        )
        .sort(-PipelineRun.updated_at)
        .to_list()
    )

    updated = 0
    failed = 0
    details: list[dict[str, str]] = []

    for run in runs:
        try:
            await classify_and_store_risk_for_pipeline_run(
                workspace=ws,
                pipeline_run=run,
            )
            updated += 1
        except Exception as exc:
            failed += 1
            run.risk_status = "failed"
            run.risk_error = str(exc)
            run.updated_at = datetime.now(timezone.utc)
            await run.save()
            details.append(
                {
                    "run_id": str(run.run_id or ""),
                    "workflow_name": run.workflow_name or "",
                    "error": str(exc),
                }
            )

    return {
        "processed": len(runs),
        "updated": updated,
        "failed": failed,
        "details": details[:10],
    }


@router.post("/{workspace_id}/diagnosis/{pipeline_run_id}/run-autofix")
async def run_autofix_for_diagnosis_report(
    workspace_id: str,
    pipeline_run_id: str,
    user: User = Depends(get_current_user),
):
    ws = await Workspace.get(PydanticObjectId(workspace_id))
    if ws is None or ws.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    run = await PipelineRun.get(PydanticObjectId(pipeline_run_id))
    if run is None or run.workspace_id != ws.id:
        raise HTTPException(status_code=404, detail="Diagnosis report not found")

    if run.event_type != "workflow_run":
        raise HTTPException(status_code=400, detail="Auto-fix can only run on workflow run reports")

    if run.diagnosis_status != "completed":
        raise HTTPException(status_code=400, detail="Diagnosis is not completed for this report")

    if run.health_status != "failing":
        raise HTTPException(status_code=400, detail="Auto-fix is only available for failing reports")

    if run.risk_status != "completed":
        try:
            await classify_and_store_risk_for_pipeline_run(
                workspace=ws,
                pipeline_run=run,
            )
        except Exception as exc:
            run.risk_status = "failed"
            run.risk_error = str(exc)
            run.updated_at = datetime.now(timezone.utc)
            await run.save()
            raise HTTPException(status_code=400, detail=f"Risk classification failed: {exc}")

    try:
        execution = await execute_autofix_policy(
            workspace=ws,
            pipeline_run=run,
        )
    except Exception as exc:
        run.autofix_status = "failed"
        run.autofix_error = str(exc)
        run.updated_at = datetime.now(timezone.utc)
        await run.save()
        raise HTTPException(status_code=500, detail=f"Auto-fix execution failed: {exc}")

    refreshed_run = await PipelineRun.get(run.id)
    return {
        "pipeline_run": serialize_pipeline_run(refreshed_run or run),
        "execution_id": str(execution.id) if execution else None,
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
    if body.slack_devops_mention is not None:
        ws.slack_devops_mention = body.slack_devops_mention
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
