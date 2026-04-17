from datetime import datetime, timezone
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class AutoFixExecution(Document):
    workspace_id: PydanticObjectId
    pipeline_run_id: PydanticObjectId
    repository_full_name: str
    target_branch: str
    error_signature: str
    risk_score: int
    policy_action: str
    execution_status: str = "pending"
    reviewer_username: Optional[str] = None
    reviewer_github_id: Optional[int] = None
    mode: str = "report_only"
    proposed_fix_json: dict[str, Any] = Field(default_factory=dict)
    report_json: dict[str, Any] = Field(default_factory=dict)
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    pr_state: Optional[str] = None
    fix_branch: Optional[str] = None
    merge_sha: Optional[str] = None
    loop_blocked_reason: Optional[str] = None
    signed_report_token: Optional[str] = None
    report_feedback_status: Optional[str] = None
    report_feedback_note: Optional[str] = None
    resolution_feedback_status: Optional[str] = None
    resolution_feedback_url: Optional[str] = None
    resolution_feedback_requested_at: Optional[datetime] = None
    resolution_feedback_submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "autofix_executions"
        use_state_management = True
