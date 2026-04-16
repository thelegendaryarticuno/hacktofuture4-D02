"""
Workspace document — a logical container that groups repositories for a user.
"""

from datetime import datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


class RiskProfile(BaseModel):
    production_branch: str = "main"
    require_approval_above: int = 60
    auto_fix_below: int = 30


class Workspace(Document):
    """A named workspace owned by a user, containing connected repositories."""

    name: str
    description: Optional[str] = None
    owner_id: PydanticObjectId  # references User._id
    github_installation_id: Optional[int] = None
    github_repository_id: Optional[int] = None
    github_repo_full_name: Optional[str] = None
    github_default_branch: Optional[str] = None
    github_repo_private: Optional[bool] = None
    github_repo_html_url: Optional[str] = None
    github_account_login: Optional[str] = None
    github_account_type: Optional[str] = None
    risk_profile: RiskProfile = Field(default_factory=RiskProfile)
    connected_at: Optional[datetime] = None
    last_webhook_event_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "workspaces"
        use_state_management = True
