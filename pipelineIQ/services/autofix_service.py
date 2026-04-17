from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from jose import JWTError, jwt

from config import settings
from models.autofix_execution import AutoFixExecution
from models.autofix_feedback import AutoFixFeedback
from models.autofix_memory import AutoFixMemory
from models.pipeline_run import PipelineRun
from models.user import User
from models.workspace import Workspace
from services.github_app import (
    close_pull_request,
    create_branch_ref,
    create_pull_request,
    fetch_file_contents,
    get_branch_head_sha,
    merge_pull_request,
    request_pull_request_reviewers,
    update_file_contents,
)
from services.llm_gateway import call_with_fallback
from services.risk_classifier import fetch_compare_details_for_pipeline_run
from services.slack_notifier import post_slack_message

AUTOFIX_SYSTEM_PROMPT = """
You are the PipelineIQ Auto Fix Agent.

Your job is to propose the smallest safe code change that fixes the diagnosed deployment issue.

Rules:
- Return valid JSON only.
- Modify at most 3 files.
- Prefer the smallest change that directly fixes the issue.
- Do not touch unrelated files.
- Keep existing style and structure.
- If you are not confident, return an empty files array and explain why in summary.

Return JSON with keys:
{
  "summary": "one paragraph explaining the fix",
  "rationale": "why this change should resolve the failure",
  "commit_title": "short git commit title",
  "pull_request_title": "short PR title",
  "pull_request_body": "markdown body",
  "possible_fix_steps": ["step 1", "step 2"],
  "files": [
    {
      "path": "relative/path.py",
      "content": "full new file content"
    }
  ]
}
""".strip()


def build_error_signature(pipeline_run: PipelineRun) -> str:
    diagnosis = pipeline_run.diagnosis_report_json or {}
    error_type = str(diagnosis.get("error_type") or "").strip().lower()
    cause = ""
    possible_causes = diagnosis.get("possible_causes") or []
    if possible_causes:
        cause = str(possible_causes[0]).strip().lower()
    signature = f"{error_type}|{cause}"
    signature = re.sub(r"\s+", " ", signature)
    return signature[:500]


def _event_branch_candidates(pipeline_run: PipelineRun) -> list[str]:
    raw_event = pipeline_run.raw_event or {}
    workflow_run = raw_event.get("workflow_run") or {}
    repository = raw_event.get("repository") or {}
    pull_requests = workflow_run.get("pull_requests") or []
    pull_request = pull_requests[0] if pull_requests else {}

    candidates = [
        pipeline_run.branch,
        workflow_run.get("head_branch"),
        ((pull_request.get("head") or {}).get("ref")),
        ((pull_request.get("base") or {}).get("ref")),
        repository.get("default_branch"),
    ]
    return [candidate.strip() for candidate in candidates if isinstance(candidate, str) and candidate.strip()]


def _target_branch(pipeline_run: PipelineRun, workspace: Workspace) -> str:
    candidates = [
        * _event_branch_candidates(pipeline_run),
        workspace.github_default_branch,
        workspace.risk_profile.production_branch,
        "main",
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "main"


def _report_url(token: str) -> str:
    return f"{settings.FRONTEND_URL}/autofix/report?token={token}"


def _feedback_url(token: str) -> str:
    return f"{settings.FRONTEND_URL}/autofix/feedback?token={token}"


def create_autofix_report_token(execution_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "autofix_report",
        "execution_id": execution_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.AUTOFIX_REPORT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_autofix_feedback_token(execution_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "autofix_feedback",
        "execution_id": execution_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.AUTOFIX_FEEDBACK_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_autofix_report_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "autofix_report":
        raise JWTError("Invalid autofix report token")
    return payload


def decode_autofix_feedback_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != "autofix_feedback":
        raise JWTError("Invalid autofix feedback token")
    return payload


async def _memory_context(workspace: Workspace, repository_full_name: str, error_signature: str) -> list[AutoFixMemory]:
    memories = await AutoFixMemory.find(
        AutoFixMemory.workspace_id == workspace.id,
        AutoFixMemory.repository_full_name == repository_full_name,
        AutoFixMemory.error_signature == error_signature,
    ).sort(-AutoFixMemory.updated_at).limit(5).to_list()
    return memories


async def _allow_automerge_from_memory(workspace: Workspace, repository_full_name: str, error_signature: str) -> bool:
    memories = await _memory_context(workspace, repository_full_name, error_signature)
    return any(memory.approved_for_auto_merge for memory in memories)


async def _feedback_context(workspace: Workspace, repository_full_name: str, error_signature: str) -> list[AutoFixFeedback]:
    return await AutoFixFeedback.find(
        AutoFixFeedback.workspace_id == workspace.id,
        AutoFixFeedback.repository_full_name == repository_full_name,
        AutoFixFeedback.error_signature == error_signature,
        AutoFixFeedback.status == "submitted",
    ).sort(-AutoFixFeedback.updated_at).limit(5).to_list()


async def _loop_guard(workspace: Workspace, pipeline_run: PipelineRun, error_signature: str) -> str | None:
    # Loop guard disabled: allow repeated attempts on the same branch/signature.
    return None


async def _candidate_files(pipeline_run: PipelineRun) -> list[dict[str, Any]]:
    compare_details = await fetch_compare_details_for_pipeline_run(pipeline_run)
    ref = (pipeline_run.commit_sha or "").strip() or None
    if ref is None:
        raw_event = pipeline_run.raw_event or {}
        workflow_run = raw_event.get("workflow_run") or {}
        ref = (workflow_run.get("head_sha") or "").strip() or None

    files: list[dict[str, Any]] = []
    for path in list(compare_details.get("changed_files") or [])[:3]:
        try:
            content = await fetch_file_contents(
                installation_id=pipeline_run.installation_id,
                repository_full_name=pipeline_run.repository_full_name,
                path=path,
                ref=ref or "",
            )
            files.append(content)
        except Exception:
            continue
    return files


def _autofix_prompt(
    *,
    pipeline_run: PipelineRun,
    risk_score: int,
    risk_band: str,
    candidate_files: list[dict[str, Any]],
    memories: list[AutoFixMemory],
    feedback_entries: list[AutoFixFeedback],
) -> str:
    diagnosis = pipeline_run.diagnosis_report_json or {}
    memory_lines = [
        {
            "type": memory.memory_type,
            "approved_for_auto_merge": memory.approved_for_auto_merge,
            "note": memory.note,
        }
        for memory in memories
    ]
    feedback_lines = [
        {
            "outcome": feedback.outcome,
            "automation_quality": feedback.automation_quality,
            "should_auto_apply_similar": feedback.should_auto_apply_similar,
            "notes": feedback.notes,
        }
        for feedback in feedback_entries
    ]
    payload = {
        "repository": pipeline_run.repository_full_name,
        "branch": next(iter(_event_branch_candidates(pipeline_run)), pipeline_run.branch),
        "risk_score": risk_score,
        "risk_band": risk_band,
        "error_summary": pipeline_run.error_summary,
        "diagnosis": diagnosis,
        "candidate_files": [
            {
                "path": item["path"],
                "content": item["content"],
            }
            for item in candidate_files
        ],
        "past_reviewer_feedback": memory_lines,
        "post_resolution_feedback": feedback_lines,
    }
    return json.dumps(payload, separators=(",", ":"))


def _fallback_fix_plan(pipeline_run: PipelineRun, candidate_files: list[dict[str, Any]]) -> dict[str, Any]:
    diagnosis = pipeline_run.diagnosis_report_json or {}
    return {
        "summary": "PipelineIQ could not confidently generate a safe automatic patch from the available repository context.",
        "rationale": diagnosis.get("latest_working_change") or "Manual review is safer for this failure.",
        "commit_title": "pipelineiq: manual fix required",
        "pull_request_title": "PipelineIQ: manual fix required",
        "pull_request_body": "Automatic fix generation did not reach a safe confidence threshold.",
        "possible_fix_steps": [
            "Inspect the diagnosis output and compare diff.",
            "Apply the smallest manual fix to the failing file.",
            "Re-run the pipeline after review.",
        ],
        "files": [],
        "candidate_files": [item["path"] for item in candidate_files],
    }


async def generate_autofix_plan(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    risk_score: int,
    risk_band: str,
    error_signature: str,
) -> dict[str, Any]:
    candidate_files = await _candidate_files(pipeline_run)
    memories = await _memory_context(workspace, pipeline_run.repository_full_name, error_signature)
    feedback_entries = await _feedback_context(workspace, pipeline_run.repository_full_name, error_signature)

    try:
        response_text, _, _ = await call_with_fallback(
            primary_provider=settings.AUTOFIX_AGENT_PRIMARY_PROVIDER,
            primary_model=settings.AUTOFIX_AGENT_PRIMARY_MODEL,
            fallback_provider=settings.AUTOFIX_AGENT_FALLBACK_PROVIDER,
            fallback_model=settings.AUTOFIX_AGENT_FALLBACK_MODEL,
            system_prompt=AUTOFIX_SYSTEM_PROMPT,
            user_prompt=_autofix_prompt(
                pipeline_run=pipeline_run,
                risk_score=risk_score,
                risk_band=risk_band,
                candidate_files=candidate_files,
                memories=memories,
                feedback_entries=feedback_entries,
            ),
            temperature=0.1,
            max_tokens=4000,
        )
        plan = json.loads(response_text)
        if not isinstance(plan, dict):
            return _fallback_fix_plan(pipeline_run, candidate_files)
        files = plan.get("files")
        if not isinstance(files, list):
            plan["files"] = []
        else:
            plan["files"] = [
                file_item for file_item in files[:3]
                if isinstance(file_item, dict)
                and isinstance(file_item.get("path"), str)
                and isinstance(file_item.get("content"), str)
                and file_item.get("path").strip()
            ]
        return {
            "summary": str(plan.get("summary") or "").strip(),
            "rationale": str(plan.get("rationale") or "").strip(),
            "commit_title": str(plan.get("commit_title") or "pipelineiq: autofix").strip(),
            "pull_request_title": str(plan.get("pull_request_title") or "PipelineIQ autofix").strip(),
            "pull_request_body": str(plan.get("pull_request_body") or "").strip(),
            "possible_fix_steps": plan.get("possible_fix_steps") if isinstance(plan.get("possible_fix_steps"), list) else [],
            "files": plan["files"],
            "candidate_files": [item["path"] for item in candidate_files],
        }
    except Exception:
        return _fallback_fix_plan(pipeline_run, candidate_files)


def _execution_report(
    *,
    pipeline_run: PipelineRun,
    target_branch: str,
    fix_plan: dict[str, Any],
    risk_score: int,
    risk_band: str,
    mode: str,
    report_url: str,
    reviewer: User | None,
    policy_note: str,
    loop_blocked_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "repository": pipeline_run.repository_full_name,
        "branch": target_branch,
        "target_branch": target_branch,
        "commit_sha": pipeline_run.commit_sha,
        "workflow_name": pipeline_run.workflow_name,
        "risk_score": risk_score,
        "risk_band": risk_band,
        "mode": mode,
        "policy_note": policy_note,
        "loop_blocked_reason": loop_blocked_reason,
        "diagnosis": pipeline_run.diagnosis_report_json or {},
        "risk": pipeline_run.risk_report_json or {},
        "possible_fix_steps": fix_plan.get("possible_fix_steps") or [],
        "fix_summary": fix_plan.get("summary") or "",
        "fix_rationale": fix_plan.get("rationale") or "",
        "candidate_files": fix_plan.get("candidate_files") or [],
        "proposed_files": [item.get("path") for item in fix_plan.get("files") or []],
        "reviewer": {
            "username": reviewer.username if reviewer else None,
            "github_id": reviewer.github_id if reviewer else None,
        },
        "report_url": report_url,
    }


def _error_brief(pipeline_run: PipelineRun) -> str:
    summary = (pipeline_run.error_summary or "").strip()
    if summary:
        lines = [line.strip() for line in summary.splitlines() if line.strip()]
        return " | ".join(lines[:2])
    diagnosis = pipeline_run.diagnosis_report_json or {}
    causes = diagnosis.get("possible_causes") or []
    if causes and isinstance(causes[0], str):
        return causes[0].strip()
    return "Failure details were captured from the pipeline run logs."


def _fix_brief(fix_plan: dict[str, Any]) -> str:
    return str(fix_plan.get("summary") or fix_plan.get("rationale") or "Automatic fix summary unavailable.").strip()


def _error_file(fix_plan: dict[str, Any]) -> str:
    proposed = fix_plan.get("files") or []
    if proposed and isinstance(proposed[0], dict):
        path = str(proposed[0].get("path") or "").strip()
        if path:
            return path
    candidates = fix_plan.get("candidate_files") or []
    if candidates and isinstance(candidates[0], str):
        return candidates[0]
    return "unknown"


def _slack_target(workspace: Workspace) -> str:
    mention = (workspace.slack_devops_mention or settings.SLACK_DEVOPS_MENTION_DEFAULT or "").strip()
    return mention


async def _notify_autofix_slack(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    execution: AutoFixExecution,
    fix_plan: dict[str, Any],
    include_report_url: bool,
    title: str,
) -> None:
    mention = _slack_target(workspace)
    mention_line = f"Engineer: {mention}\n" if mention else ""
    report_url = execution.report_json.get("report_url") if isinstance(execution.report_json, dict) else None
    lines = [
        f"{title}",
        mention_line.rstrip(),
        f"Repository: {pipeline_run.repository_full_name}",
        f"Workflow: {pipeline_run.workflow_name or 'workflow_run'}",
        f"Branch: {execution.target_branch}",
        f"Risk: {execution.risk_score} ({pipeline_run.risk_band or 'unknown'})",
        f"Status: {execution.execution_status}",
        f"Error brief: {_error_brief(pipeline_run)}",
        f"Error file: {_error_file(fix_plan)}",
        f"Fix brief: {_fix_brief(fix_plan)}",
    ]
    if execution.pr_url:
        lines.append(f"PR: {execution.pr_url}")
    if include_report_url and report_url:
        lines.append(f"Signed approval URL: {report_url}")

    text = "\n".join(line for line in lines if line)
    try:
        await post_slack_message(text=text)
    except Exception as exc:
        logging.getLogger(__name__).error(f"Failed to send Slack: {exc}")


async def _ensure_resolution_feedback_request(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    execution: AutoFixExecution,
    reviewer: User | None,
) -> tuple[AutoFixFeedback, bool]:
    existing = await AutoFixFeedback.find_one(AutoFixFeedback.execution_id == execution.id)
    if existing is not None:
        return existing, False

    token = create_autofix_feedback_token(str(execution.id))
    url = _feedback_url(token)
    now = datetime.now(timezone.utc)
    feedback = AutoFixFeedback(
        workspace_id=workspace.id,
        execution_id=execution.id,
        pipeline_run_id=pipeline_run.id,
        repository_full_name=pipeline_run.repository_full_name,
        error_signature=execution.error_signature,
        target_branch=execution.target_branch,
        reviewer_username=reviewer.username if reviewer else None,
        reviewer_github_id=reviewer.github_id if reviewer else None,
        feedback_token=token,
        feedback_url=url,
        status="requested",
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    await feedback.insert()

    execution.resolution_feedback_status = "requested"
    execution.resolution_feedback_url = url
    execution.resolution_feedback_requested_at = now
    execution.updated_at = now
    await execution.save()

    pipeline_run.autofix_feedback_status = "requested"
    pipeline_run.autofix_feedback_url = url
    pipeline_run.updated_at = now
    await pipeline_run.save()
    return feedback, True


async def _notify_resolution_feedback_slack(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    execution: AutoFixExecution,
    feedback: AutoFixFeedback,
) -> None:
    mention = _slack_target(workspace)
    lines = [
        "PipelineIQ post-fix feedback requested",
        mention,
        f"Repository: {pipeline_run.repository_full_name}",
        f"Workflow: {pipeline_run.workflow_name or 'workflow_run'}",
        f"Branch: {execution.target_branch}",
        f"PR: {execution.pr_url or 'n/a'}",
        "The auto-fix has been merged. Please share how well it actually worked so PipelineIQ can learn from this case.",
        f"Feedback form: {feedback.feedback_url}",
    ]
    text = "\n".join(line for line in lines if line)
    try:
        await post_slack_message(text=text)
    except Exception as exc:
        logging.getLogger(__name__).error(f"Failed to send Slack feedback request: {exc}")


async def _create_fix_pr(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    execution: AutoFixExecution,
    fix_plan: dict[str, Any],
    reviewer: User | None,
    auto_merge: bool,
) -> AutoFixExecution:
    target_branch = _target_branch(pipeline_run, workspace)
    branch_sha = await get_branch_head_sha(
        installation_id=pipeline_run.installation_id,
        repository_full_name=pipeline_run.repository_full_name,
        branch_name=target_branch,
    )
    fix_branch = f"pipelineiq/autofix-{pipeline_run.run_id or 'run'}-{execution.id}".replace(" ", "-")
    await create_branch_ref(
        installation_id=pipeline_run.installation_id,
        repository_full_name=pipeline_run.repository_full_name,
        branch_name=fix_branch,
        from_sha=branch_sha,
    )

    changed_paths: list[str] = []
    for file_item in fix_plan.get("files") or []:
        existing = await fetch_file_contents(
            installation_id=pipeline_run.installation_id,
            repository_full_name=pipeline_run.repository_full_name,
            path=file_item["path"],
            ref=target_branch,
        )
        await update_file_contents(
            installation_id=pipeline_run.installation_id,
            repository_full_name=pipeline_run.repository_full_name,
            path=file_item["path"],
            branch_name=fix_branch,
            previous_sha=existing["sha"],
            new_content=file_item["content"],
            commit_message=fix_plan.get("commit_title") or "pipelineiq: autofix",
        )
        changed_paths.append(file_item["path"])

    pr = await create_pull_request(
        installation_id=pipeline_run.installation_id,
        repository_full_name=pipeline_run.repository_full_name,
        title=fix_plan.get("pull_request_title") or "PipelineIQ autofix",
        body=fix_plan.get("pull_request_body") or "",
        head_branch=fix_branch,
        base_branch=target_branch,
    )

    pr_number = pr.get("number")
    pr_url = pr.get("html_url")
    if reviewer and not auto_merge:
        try:
            await request_pull_request_reviewers(
                installation_id=pipeline_run.installation_id,
                repository_full_name=pipeline_run.repository_full_name,
                pull_number=pr_number,
                reviewers=[reviewer.username],
            )
        except Exception:
            pass

    execution.fix_branch = fix_branch
    execution.pr_number = pr_number
    execution.pr_url = pr_url
    execution.pr_state = pr.get("state")
    execution.report_json["proposed_files"] = changed_paths
    execution.execution_status = "pr_open"
    execution.updated_at = datetime.now(timezone.utc)

    if auto_merge:
        merge = await merge_pull_request(
            installation_id=pipeline_run.installation_id,
            repository_full_name=pipeline_run.repository_full_name,
            pull_number=pr_number,
            commit_title=fix_plan.get("commit_title") or "pipelineiq: autofix",
        )
        execution.execution_status = "merged"
        execution.pr_state = "merged"
        execution.merge_sha = merge.get("sha")
        execution.updated_at = datetime.now(timezone.utc)

    await execution.save()
    return execution


async def store_feedback_memory(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    reviewer: User | None,
    error_signature: str,
    memory_type: str,
    note: str | None,
    approved_for_auto_merge: bool,
) -> AutoFixMemory:
    memory = AutoFixMemory(
        workspace_id=workspace.id,
        repository_full_name=pipeline_run.repository_full_name,
        error_signature=error_signature,
        memory_type=memory_type,
        reviewer_username=reviewer.username if reviewer else None,
        reviewer_github_id=reviewer.github_id if reviewer else None,
        note=note,
        approved_for_auto_merge=approved_for_auto_merge,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await memory.insert()
    return memory


async def request_resolution_feedback(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
    execution: AutoFixExecution,
    reviewer: User | None,
) -> AutoFixFeedback | None:
    if execution.execution_status != "merged" or execution.mode == "auto_merge":
        return None

    feedback, created = await _ensure_resolution_feedback_request(
        workspace=workspace,
        pipeline_run=pipeline_run,
        execution=execution,
        reviewer=reviewer,
    )
    if created:
        await _notify_resolution_feedback_slack(
            workspace=workspace,
            pipeline_run=pipeline_run,
            execution=execution,
            feedback=feedback,
        )
    return feedback


async def execute_autofix_policy(
    *,
    workspace: Workspace,
    pipeline_run: PipelineRun,
) -> AutoFixExecution | None:
    risk_score = int(pipeline_run.risk_score or 0)
    if pipeline_run.health_status != "failing":
        pipeline_run.autofix_status = "skipped"
        return None

    pipeline_run.autofix_error = None
    pipeline_run.autofix_pr_url = None
    pipeline_run.autofix_feedback_url = None
    pipeline_run.autofix_feedback_status = None

    reviewer = await User.get(workspace.owner_id)
    error_signature = build_error_signature(pipeline_run)
    target_branch = _target_branch(pipeline_run, workspace)
    loop_blocked_reason = None
    if risk_score <= workspace.risk_profile.auto_fix_below:
        mode = "auto_merge"
        policy_note = "Risk score is inside the auto-fix range."
    elif risk_score <= workspace.risk_profile.require_approval_above:
        mode = "approval_pr"
        policy_note = "Risk score requires a PR and reviewer approval before merge."
    else:
        mode = "approval_pr"
        policy_note = "High-risk change: PR is created for explicit approval, and the on-call engineer is paged with a signed approval URL."

    fix_plan = await generate_autofix_plan(
        workspace=workspace,
        pipeline_run=pipeline_run,
        risk_score=risk_score,
        risk_band=str(pipeline_run.risk_band or "unknown"),
        error_signature=error_signature,
    )

    execution = AutoFixExecution(
        workspace_id=workspace.id,
        pipeline_run_id=pipeline_run.id,
        repository_full_name=pipeline_run.repository_full_name,
        target_branch=target_branch,
        error_signature=error_signature,
        risk_score=risk_score,
        policy_action=mode,
        reviewer_username=reviewer.username if reviewer else None,
        reviewer_github_id=reviewer.github_id if reviewer else None,
        mode=mode,
        proposed_fix_json=fix_plan,
        execution_status="awaiting_human_decision" if mode == "report_only" else "pending",
        loop_blocked_reason=loop_blocked_reason,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await execution.insert()

    token = create_autofix_report_token(str(execution.id))
    report_url = _report_url(token)
    execution.signed_report_token = token
    execution.report_json = _execution_report(
        pipeline_run=pipeline_run,
        target_branch=target_branch,
        fix_plan=fix_plan,
        risk_score=risk_score,
        risk_band=str(pipeline_run.risk_band or "unknown"),
        mode=mode,
        report_url=report_url,
        reviewer=reviewer,
        policy_note=policy_note,
        loop_blocked_reason=loop_blocked_reason,
    )
    await execution.save()

    pipeline_run.autofix_execution_id = str(execution.id)
    pipeline_run.autofix_mode = mode
    pipeline_run.autofix_report_url = report_url

    if mode == "report_only" or not fix_plan.get("files"):
        if not fix_plan.get("files") and mode != "report_only":
            execution.execution_status = "manual_review_required"
            execution.updated_at = datetime.now(timezone.utc)
            await execution.save()
        pipeline_run.autofix_status = execution.execution_status
        pipeline_run.autofix_error = None if fix_plan.get("files") else "No safe minimal patch was generated automatically."
        pipeline_run.updated_at = datetime.now(timezone.utc)
        await pipeline_run.save()
        await _notify_autofix_slack(
            workspace=workspace,
            pipeline_run=pipeline_run,
            execution=execution,
            fix_plan=fix_plan,
            include_report_url=True,
            title="PipelineIQ manual review requested" if not fix_plan.get("files") else "PipelineIQ report-only decision",
        )
        return execution

    try:
        execution = await _create_fix_pr(
            workspace=workspace,
            pipeline_run=pipeline_run,
            execution=execution,
            fix_plan=fix_plan,
            reviewer=reviewer,
            auto_merge=mode == "auto_merge",
        )
        pipeline_run.autofix_status = execution.execution_status
        pipeline_run.autofix_pr_url = execution.pr_url
        pipeline_run.autofix_error = None
    except Exception as exc:
        execution.execution_status = "failed"
        execution.report_feedback_note = str(exc)
        execution.updated_at = datetime.now(timezone.utc)
        await execution.save()
        pipeline_run.autofix_status = "failed"
        pipeline_run.autofix_error = str(exc)

    pipeline_run.updated_at = datetime.now(timezone.utc)
    await pipeline_run.save()

    await _notify_autofix_slack(
        workspace=workspace,
        pipeline_run=pipeline_run,
        execution=execution,
        fix_plan=fix_plan,
        include_report_url=mode == "approval_pr",
        title=(
            "PipelineIQ high-risk approval required (paged)"
            if risk_score > int(workspace.risk_profile.require_approval_above)
            else "PipelineIQ auto-fix execution update"
        ),
    )

    await request_resolution_feedback(
        workspace=workspace,
        pipeline_run=pipeline_run,
        execution=execution,
        reviewer=reviewer,
    )

    return execution


async def get_autofix_execution_by_token(token: str) -> AutoFixExecution:
    payload = decode_autofix_report_token(token)
    execution = await AutoFixExecution.get(payload["execution_id"])
    if execution is None:
        raise JWTError("Auto-fix report not found")
    return execution


async def get_autofix_feedback_by_token(token: str) -> AutoFixFeedback:
    payload = decode_autofix_feedback_token(token)
    feedback = await AutoFixFeedback.find_one(AutoFixFeedback.feedback_token == token)
    if feedback is None or str(feedback.execution_id) != str(payload["execution_id"]):
        raise JWTError("Auto-fix feedback request not found")
    return feedback


async def handle_report_feedback(
    *,
    token: str,
    decision: str,
    note: str | None = None,
) -> dict[str, Any]:
    execution = await get_autofix_execution_by_token(token)
    pipeline_run = await PipelineRun.get(execution.pipeline_run_id)
    workspace = await Workspace.get(execution.workspace_id)
    reviewer = await User.get(workspace.owner_id) if workspace else None
    if pipeline_run is None or workspace is None:
        raise JWTError("Associated pipeline run or workspace was not found")

    normalized = decision.strip().lower()
    if normalized not in {"approve", "reject"}:
        raise JWTError("Decision must be approve or reject")

    if execution.mode == "approval_pr":
        if normalized == "approve":
            if execution.pr_number and execution.pr_state != "merged":
                if not pipeline_run.installation_id:
                    raise JWTError("Missing installation context for PR merge")
                merge = await merge_pull_request(
                    installation_id=pipeline_run.installation_id,
                    repository_full_name=pipeline_run.repository_full_name,
                    pull_number=execution.pr_number,
                    commit_title=(execution.proposed_fix_json or {}).get("commit_title") or "pipelineiq: autofix",
                )
                execution.execution_status = "merged"
                execution.pr_state = "merged"
                execution.merge_sha = merge.get("sha")
            await store_feedback_memory(
                workspace=workspace,
                pipeline_run=pipeline_run,
                reviewer=reviewer,
                error_signature=execution.error_signature,
                memory_type="future_auto_merge",
                note=note,
                approved_for_auto_merge=True,
            )
            execution.report_feedback_status = "approved_and_merged"
        else:
            if execution.pr_number and execution.pr_state not in {"closed", "merged"}:
                if not pipeline_run.installation_id:
                    raise JWTError("Missing installation context for PR close")
                await close_pull_request(
                    installation_id=pipeline_run.installation_id,
                    repository_full_name=pipeline_run.repository_full_name,
                    pull_number=execution.pr_number,
                )
                execution.execution_status = "closed_without_merge"
                execution.pr_state = "closed"
            await store_feedback_memory(
                workspace=workspace,
                pipeline_run=pipeline_run,
                reviewer=reviewer,
                error_signature=execution.error_signature,
                memory_type="future_manual_only",
                note=note,
                approved_for_auto_merge=False,
            )
            execution.report_feedback_status = "rejected_and_closed"
        execution.report_feedback_note = note
        execution.updated_at = datetime.now(timezone.utc)
        await execution.save()

        pipeline_run.autofix_status = execution.execution_status
        pipeline_run.autofix_pr_url = execution.pr_url
        pipeline_run.updated_at = datetime.now(timezone.utc)
        await pipeline_run.save()

        await _notify_autofix_slack(
            workspace=workspace,
            pipeline_run=pipeline_run,
            execution=execution,
            fix_plan=execution.proposed_fix_json or {},
            include_report_url=False,
            title="PipelineIQ approval decision received",
        )

        await request_resolution_feedback(
            workspace=workspace,
            pipeline_run=pipeline_run,
            execution=execution,
            reviewer=reviewer,
        )

        return {"status": execution.report_feedback_status, "pr_url": execution.pr_url}

    if normalized == "approve" and execution.mode == "report_only":
        if execution.pr_url is None and execution.proposed_fix_json.get("files"):
            execution = await _create_fix_pr(
                workspace=workspace,
                pipeline_run=pipeline_run,
                execution=execution,
                fix_plan=execution.proposed_fix_json,
                reviewer=reviewer,
                auto_merge=False,
            )
        execution.report_feedback_status = "approved_create_pr"
    else:
        await store_feedback_memory(
            workspace=workspace,
            pipeline_run=pipeline_run,
            reviewer=reviewer,
            error_signature=execution.error_signature,
            memory_type="rejected_fix",
            note=note,
            approved_for_auto_merge=False,
        )
        execution.report_feedback_status = "rejected"

    execution.report_feedback_note = note
    execution.updated_at = datetime.now(timezone.utc)
    await execution.save()

    pipeline_run.autofix_status = execution.execution_status
    pipeline_run.autofix_pr_url = execution.pr_url
    pipeline_run.updated_at = datetime.now(timezone.utc)
    await pipeline_run.save()
    return {"status": execution.report_feedback_status, "pr_url": execution.pr_url}


async def handle_resolution_feedback_submission(
    *,
    token: str,
    outcome: str,
    automation_quality: str,
    should_auto_apply_similar: bool,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_outcome = outcome.strip().lower()
    normalized_quality = automation_quality.strip().lower()
    allowed_outcomes = {"resolved", "partially_resolved", "not_resolved"}
    allowed_qualities = {"excellent", "acceptable", "poor"}
    if normalized_outcome not in allowed_outcomes:
        raise JWTError("Outcome must be resolved, partially_resolved, or not_resolved")
    if normalized_quality not in allowed_qualities:
        raise JWTError("Automation quality must be excellent, acceptable, or poor")

    feedback = await get_autofix_feedback_by_token(token)
    execution = await AutoFixExecution.get(feedback.execution_id)
    pipeline_run = await PipelineRun.get(feedback.pipeline_run_id)
    workspace = await Workspace.get(feedback.workspace_id)
    reviewer = await User.get(workspace.owner_id) if workspace else None
    if execution is None or pipeline_run is None or workspace is None:
        raise JWTError("Associated auto-fix context was not found")

    now = datetime.now(timezone.utc)
    feedback.status = "submitted"
    feedback.outcome = normalized_outcome
    feedback.automation_quality = normalized_quality
    feedback.should_auto_apply_similar = should_auto_apply_similar
    feedback.notes = notes
    feedback.submitted_at = now
    feedback.updated_at = now
    await feedback.save()

    execution.resolution_feedback_status = "submitted"
    execution.resolution_feedback_submitted_at = now
    execution.updated_at = now
    await execution.save()

    pipeline_run.autofix_feedback_status = "submitted"
    pipeline_run.updated_at = now
    await pipeline_run.save()

    memory_note_parts = [
        f"Outcome: {normalized_outcome}",
        f"Quality: {normalized_quality}",
        f"Reuse similar fix automatically: {'yes' if should_auto_apply_similar else 'no'}",
    ]
    if notes and notes.strip():
        memory_note_parts.append(f"Engineer feedback: {notes.strip()}")
    memory_note = " | ".join(memory_note_parts)
    approved_for_auto_merge = (
        normalized_outcome == "resolved"
        and normalized_quality in {"excellent", "acceptable"}
        and should_auto_apply_similar
    )
    memory_type = "resolution_feedback_positive" if approved_for_auto_merge else "resolution_feedback_negative"
    await store_feedback_memory(
        workspace=workspace,
        pipeline_run=pipeline_run,
        reviewer=reviewer,
        error_signature=execution.error_signature,
        memory_type=memory_type,
        note=memory_note,
        approved_for_auto_merge=approved_for_auto_merge,
    )

    return {
        "status": "submitted",
        "feedback_status": feedback.status,
        "execution_status": execution.execution_status,
    }
