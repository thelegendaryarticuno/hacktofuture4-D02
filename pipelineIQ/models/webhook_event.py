"""
Stored GitHub webhook deliveries for later agent processing.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class WebhookEvent(Document):
    delivery_id: str
    event_type: str
    action: Optional[str] = None
    installation_id: Optional[int] = None
    repository_full_name: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "webhook_events"
        use_state_management = True
