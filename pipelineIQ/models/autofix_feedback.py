from datetime import datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class AutoFixFeedback(Document):
    workspace_id: PydanticObjectId
    execution_id: PydanticObjectId
    pipeline_run_id: PydanticObjectId
    repository_full_name: str
    error_signature: str
    target_branch: str
    reviewer_username: Optional[str] = None
    reviewer_github_id: Optional[int] = None
    feedback_token: str
    feedback_url: str
    status: str = "requested"
    outcome: Optional[str] = None
    automation_quality: Optional[str] = None
    should_auto_apply_similar: Optional[bool] = None
    notes: Optional[str] = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "autofix_feedbacks"
        use_state_management = True
