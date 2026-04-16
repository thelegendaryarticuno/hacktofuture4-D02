from datetime import datetime, timezone
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class PipelineRun(Document):
    workspace_id: PydanticObjectId
    installation_id: Optional[int] = None
    repository_full_name: str
    delivery_id: str
    event_type: str
    action: Optional[str] = None
    run_id: Optional[int] = None
    workflow_status: Optional[str] = None
    workflow_name: Optional[str] = None
    workflow_url: Optional[str] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    triggered_by: Optional[str] = None
    conclusion: Optional[str] = None
    health_status: str = "unknown"
    kafka_status: str = "queued"
    monitor_status: str = "pending"
    diagnosis_status: str = "pending"
    monitor_summary: Optional[str] = None
    monitor_report_json: dict[str, Any] = Field(default_factory=dict)
    monitor_logs_excerpt: list[str] = Field(default_factory=list)
    diagnosis_report: Optional[str] = None
    diagnosis_report_json: dict[str, Any] = Field(default_factory=dict)
    diagnosis_error: Optional[str] = None
    error_summary: Optional[str] = None
    diagnosis_provider: Optional[str] = None
    diagnosis_model: Optional[str] = None
    monitor_provider: Optional[str] = None
    monitor_model: Optional[str] = None
    raw_event: dict[str, Any] = Field(default_factory=dict)
    enriched_event: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "pipeline_runs"
        use_state_management = True
