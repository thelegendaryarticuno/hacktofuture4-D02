import httpx

from fastapi import APIRouter, HTTPException
from jose import JWTError
from pydantic import BaseModel

from models.autofix_execution import AutoFixExecution
from models.pipeline_run import PipelineRun
from services.autofix_service import (
    get_autofix_execution_by_token,
    get_autofix_feedback_by_token,
    handle_report_feedback,
    handle_resolution_feedback_submission,
)

router = APIRouter(prefix="/api/autofix", tags=["autofix"])


class AutoFixDecisionBody(BaseModel):
    decision: str
    note: str | None = None


class AutoFixResolutionFeedbackBody(BaseModel):
    outcome: str
    automation_quality: str
    should_auto_apply_similar: bool
    notes: str | None = None


@router.get("/report")
async def get_autofix_report(token: str):
    try:
        execution = await get_autofix_execution_by_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    pipeline_run = await PipelineRun.get(execution.pipeline_run_id)
    return {
        "execution": {
            "id": str(execution.id),
            "mode": execution.mode,
            "policy_action": execution.policy_action,
            "execution_status": execution.execution_status,
            "pr_number": execution.pr_number,
            "pr_url": execution.pr_url,
            "fix_branch": execution.fix_branch,
            "report_feedback_status": execution.report_feedback_status,
            "report_feedback_note": execution.report_feedback_note,
            "reviewer_username": execution.reviewer_username,
            "reviewer_github_id": execution.reviewer_github_id,
            "target_branch": execution.target_branch,
            "loop_blocked_reason": execution.loop_blocked_reason,
            "resolution_feedback_status": execution.resolution_feedback_status,
            "resolution_feedback_url": execution.resolution_feedback_url,
            "report": execution.report_json,
            "proposed_fix": execution.proposed_fix_json,
            "created_at": execution.created_at.isoformat(),
            "updated_at": execution.updated_at.isoformat(),
        },
        "pipeline_run": {
            "workflow_name": pipeline_run.workflow_name if pipeline_run else None,
            "branch": pipeline_run.branch if pipeline_run else None,
            "commit_sha": pipeline_run.commit_sha if pipeline_run else None,
            "diagnosis": pipeline_run.diagnosis_report_json if pipeline_run else {},
            "risk": pipeline_run.risk_report_json if pipeline_run else {},
        },
    }


@router.post("/report/decision")
async def submit_autofix_report_decision(token: str, body: AutoFixDecisionBody):
    try:
        return await handle_report_feedback(
            token=token,
            decision=body.decision,
            note=body.note,
        )
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise HTTPException(status_code=403, detail="GitHub App is forbidden. Ensure 'Contents: Write' and 'Pull Requests: Write' permissions are granted in Developer Settings.")
        raise HTTPException(status_code=500, detail=f"GitHub API Error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(exc)}")


@router.get("/feedback")
async def get_autofix_feedback(token: str):
    try:
        feedback = await get_autofix_feedback_by_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    execution = await AutoFixExecution.get(feedback.execution_id)
    pipeline_run = await PipelineRun.get(feedback.pipeline_run_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Associated auto-fix execution not found")

    return {
        "feedback": {
            "id": str(feedback.id),
            "status": feedback.status,
            "outcome": feedback.outcome,
            "automation_quality": feedback.automation_quality,
            "should_auto_apply_similar": feedback.should_auto_apply_similar,
            "notes": feedback.notes,
            "feedback_url": feedback.feedback_url,
            "requested_at": feedback.requested_at.isoformat(),
            "submitted_at": feedback.submitted_at.isoformat() if feedback.submitted_at else None,
        },
        "execution": {
            "id": str(execution.id),
            "execution_status": execution.execution_status,
            "mode": execution.mode,
            "pr_url": execution.pr_url,
            "target_branch": execution.target_branch,
            "reviewer_username": execution.reviewer_username,
            "risk_score": execution.risk_score,
            "fix_summary": (execution.report_json or {}).get("fix_summary") or (execution.proposed_fix_json or {}).get("summary"),
        },
        "pipeline_run": {
            "repository_full_name": pipeline_run.repository_full_name if pipeline_run else None,
            "workflow_name": pipeline_run.workflow_name if pipeline_run else None,
            "branch": pipeline_run.branch if pipeline_run else None,
            "commit_sha": pipeline_run.commit_sha if pipeline_run else None,
            "diagnosis": pipeline_run.diagnosis_report_json if pipeline_run else {},
            "risk": pipeline_run.risk_report_json if pipeline_run else {},
        },
    }


@router.post("/feedback")
async def submit_autofix_resolution_feedback(token: str, body: AutoFixResolutionFeedbackBody):
    try:
        return await handle_resolution_feedback_submission(
            token=token,
            outcome=body.outcome,
            automation_quality=body.automation_quality,
            should_auto_apply_similar=body.should_auto_apply_similar,
            notes=body.notes,
        )
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(exc)}")
