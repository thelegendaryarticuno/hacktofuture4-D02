"""
User document — represents a GitHub-authenticated user in MongoDB.
"""

from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import BaseModel, Field


class GitHubOrganization(BaseModel):
    id: int
    login: str
    avatar_url: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None


class User(Document):
    """A PipelineIQ user authenticated via GitHub OAuth."""

    github_id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    github_access_token: str  # stored server-side only, never exposed to frontend
    organizations: list[GitHubOrganization] = Field(default_factory=list)
    last_login: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    class Settings:
        name = "users"
        use_state_management = True

    class Config:
        json_schema_extra = {
            "example": {
                "github_id": 12345678,
                "username": "octocat",
                "display_name": "The Octocat",
                "email": "octocat@github.com",
                "avatar_url": "https://avatars.githubusercontent.com/u/583231",
                "is_active": True,
            }
        }
