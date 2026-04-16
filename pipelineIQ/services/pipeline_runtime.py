from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from beanie import PydanticObjectId

from config import settings
from models.pipeline_run import PipelineRun
from models.workspace import Workspace
from services.error_detection import extract_failure_snippet, has_failure_signal
from services.github_app import download_workflow_logs, fetch_compare_diff
from services.llm_gateway import call_with_fallback

logger = logging.getLogger(__name__)

SUPPORTED_PIPELINE_EVENTS = {"workflow_run"}
SUPPORTED_WORKFLOW_ACTIONS = {"completed"}

MONITOR_AGENT_PROMPT = (
    "Return only strict JSON with keys name, branch, status, time, and optional error. "
    "If status is SUCCESS, return only name, branch, status, time. "
    "If status is FAILURE, return name, branch, status, error, time. "
    "Keep error as a 2-5 line GitHub Actions style snippet."
)

DIAGNOSIS_AGENT_PROMPT = (
    "Return only strict JSON with keys name, branch, error_type, possible_causes, latest_working_change. "
    "Use monitor error log and git diff to infer the cause. Keep output short."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _to_monitor_status(conclusion_status: str, logs_text: str) -> str:
    normalized = (conclusion_status or "").strip().upper()
    if normalized == "FAILURE":
        return "FAILURE"
    if has_failure_signal(logs_text):
        return "FAILURE"
    return "SUCCESS"


def _parse_json_object(raw_response: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return fallback


def _first_diff_file(compare_text: str) -> str:
    for line in (compare_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("File:"):
            return stripped.removeprefix("File:").strip()
    return ""


def _first_change_summary(compare_text: str) -> str:
    if not compare_text:
        return "unknown change"
    first_line = compare_text.splitlines()[0].strip()
    if not first_line:
        return "unknown change"
    return first_line


def should_process_pipeline_event(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type not in SUPPORTED_PIPELINE_EVENTS:
        return False

    workflow_run = payload.get("workflow_run") or {}
    if workflow_run.get("id") is None:
        return False

    if (workflow_run.get("status") or "").lower() != "completed":
        return False

    action = (payload.get("action") or "").lower()
    if action and action not in SUPPORTED_WORKFLOW_ACTIONS:
        return False

    return True


def build_pipeline_event(
    workspace: Workspace,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str,
) -> dict[str, Any]:
    workflow_run = payload.get("workflow_run") or {}
    repository = payload.get("repository") or {}

    repo_full_name = repository.get("full_name") or workspace.github_repo_full_name or "unknown/unknown"
    run_started_at = workflow_run.get("run_started_at") or workflow_run.get("created_at")
    completed_at = workflow_run.get("updated_at") or run_started_at or _now().isoformat()

    pull_requests = workflow_run.get("pull_requests") or []
    base_sha = None
    if pull_requests:
        base_sha = ((pull_requests[0].get("base") or {}).get("sha"))

    if not base_sha:
        head_commit = workflow_run.get("head_commit") or {}
        parents = head_commit.get("parents") or []
        if parents:
            base_sha = parents[0].get("sha")

    conclusion = (workflow_run.get("conclusion") or "").upper()
    return {
        "pipeline_run_id": None,
        "workspace_id": str(workspace.id),
        "installation_id": workspace.github_installation_id,
        "delivery_id": delivery_id,
        "repo": repo_full_name,
        "run_id": workflow_run.get("id"),
        "workflow_name": workflow_run.get("name") or payload.get("workflow", {}).get("name") or "",
        "branch": workflow_run.get("head_branch") or "",
        "head_sha": workflow_run.get("head_sha") or "",
        "base_sha": base_sha or "",
        "status": conclusion or "FAILURE",
        "workflow_status": workflow_run.get("status") or "completed",
        "completed_at": completed_at,
        "run_started_at": run_started_at or "",
        "event_type": event_type,
        "action": payload.get("action") or "completed",
    }


class PipelineRuntime:
    def __init__(self) -> None:
        self.producer: AIOKafkaProducer | None = None
        self.monitor_consumer: AIOKafkaConsumer | None = None
        self.diagnosis_consumer: AIOKafkaConsumer | None = None
        self.tasks: list[asyncio.Task] = []
        self.started = False
        self.workflow_state_store: dict[str, dict[str, Any]] = {}

    def reset_state(self) -> None:
        self.workflow_state_store.clear()

    async def start(self) -> None:
        if self.started:
            return
        if not settings.KAFKA_ENABLED:
            self.started = True
            return

        self.producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        self.monitor_consumer = AIOKafkaConsumer(
            settings.KAFKA_PIPELINE_EVENTS_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_MONITOR_GROUP_ID,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        self.diagnosis_consumer = AIOKafkaConsumer(
            settings.KAFKA_DIAGNOSIS_REQUIRED_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_DIAGNOSIS_GROUP_ID,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )

        await self.producer.start()
        await self.monitor_consumer.start()
        await self.diagnosis_consumer.start()

        self.tasks = [
            asyncio.create_task(self._consume_loop(self.monitor_consumer, self._handle_monitor_event)),
            asyncio.create_task(self._consume_loop(self.diagnosis_consumer, self._handle_diagnosis_event)),
        ]
        self.started = True

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

        if self.monitor_consumer is not None:
            await self.monitor_consumer.stop()
            self.monitor_consumer = None
        if self.diagnosis_consumer is not None:
            await self.diagnosis_consumer.stop()
            self.diagnosis_consumer = None
        if self.producer is not None:
            await self.producer.stop()
            self.producer = None

        self.started = False

    async def queue_event(
        self,
        *,
        workspace: Workspace,
        event_type: str,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> PipelineRun:
        existing = await PipelineRun.find_one(PipelineRun.delivery_id == delivery_id)
        if existing is not None:
            return existing

        event = build_pipeline_event(workspace, event_type, payload, delivery_id)

        existing_run = await PipelineRun.find_one(
            PipelineRun.workspace_id == workspace.id,
            PipelineRun.event_type == "workflow_run",
            PipelineRun.run_id == event["run_id"],
        )
        if existing_run is not None:
            return existing_run

        pipeline_run = PipelineRun(
            workspace_id=workspace.id,
            installation_id=workspace.github_installation_id,
            repository_full_name=event["repo"],
            delivery_id=delivery_id,
            event_type=event_type,
            action=event["action"],
            run_id=event["run_id"],
            workflow_name=event["workflow_name"],
            branch=event["branch"],
            commit_sha=event["head_sha"],
            triggered_by="workflow_run",
            conclusion=event["status"],
            workflow_status=event["workflow_status"],
            health_status="healthy" if event["status"] == "SUCCESS" else "failing",
            raw_event=payload,
            created_at=_now(),
            updated_at=_now(),
        )
        await pipeline_run.insert()

        event["pipeline_run_id"] = str(pipeline_run.id)
        await self._publish_pipeline_event(event)

        pipeline_run.kafka_status = "published"
        pipeline_run.updated_at = _now()
        await pipeline_run.save()
        return pipeline_run

    async def _publish_pipeline_event(self, event: dict[str, Any]) -> None:
        if settings.KAFKA_ENABLED:
            if self.producer is None:
                raise RuntimeError("Kafka producer is not started")
            await self.producer.send_and_wait(
                settings.KAFKA_PIPELINE_EVENTS_TOPIC,
                json.dumps(event).encode("utf-8"),
            )
            return
        await self._handle_monitor_event(event)

    async def _publish_diagnosis_event(self, event: dict[str, Any]) -> None:
        if settings.KAFKA_ENABLED:
            if self.producer is None:
                raise RuntimeError("Kafka producer is not started")
            await self.producer.send_and_wait(
                settings.KAFKA_DIAGNOSIS_REQUIRED_TOPIC,
                json.dumps(event).encode("utf-8"),
            )
            return
        await self._handle_diagnosis_event(event)

    async def _consume_loop(self, consumer: AIOKafkaConsumer, handler) -> None:
        try:
            async for message in consumer:
                payload = json.loads(message.value.decode("utf-8"))
                try:
                    await handler(payload)
                except Exception:
                    logger.exception("Failed to process Kafka message")
        except asyncio.CancelledError:
            raise

    async def _handle_monitor_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") != "workflow_run":
            return

        pipeline_run = await PipelineRun.get(PydanticObjectId(event["pipeline_run_id"]))
        if pipeline_run is None:
            return

        logs_text = ""
        if event.get("installation_id") and event.get("repo") and event.get("run_id"):
            try:
                logs_text = await download_workflow_logs(
                    installation_id=event["installation_id"],
                    repository_full_name=event["repo"],
                    run_id=event["run_id"],
                )
            except Exception as exc:
                logs_text = f"Failed to fetch workflow logs: {exc}"

        error_snippet = extract_failure_snippet(logs_text)
        final_status = _to_monitor_status(event.get("status") or "FAILURE", logs_text)
        monitor_report = {
            "name": event.get("workflow_name") or "",
            "branch": event.get("branch") or "",
            "status": final_status,
            "time": event.get("completed_at") or _iso(_now()),
        }
        if monitor_report["status"] == "FAILURE":
            monitor_report["error"] = error_snippet

        pipeline_run.monitor_status = "completed"
        pipeline_run.monitor_report_json = monitor_report
        pipeline_run.monitor_summary = json.dumps(monitor_report, separators=(",", ":"))
        pipeline_run.monitor_logs_excerpt = [line for line in error_snippet.splitlines() if line.strip()]
        pipeline_run.monitor_provider = "deterministic"
        pipeline_run.monitor_model = "minimal"
        pipeline_run.workflow_status = event.get("workflow_status")
        pipeline_run.health_status = "healthy" if monitor_report["status"] == "SUCCESS" else "failing"
        pipeline_run.updated_at = _now()
        await pipeline_run.save()

        self.workflow_state_store[str(event.get("run_id") or pipeline_run.run_id or "")] = monitor_report

        if monitor_report["status"] != "FAILURE":
            pipeline_run.diagnosis_status = "skipped"
            pipeline_run.updated_at = _now()
            await pipeline_run.save()
            return

        pipeline_run.diagnosis_status = "queued"
        pipeline_run.error_summary = error_snippet
        pipeline_run.updated_at = _now()
        await pipeline_run.save()

        await self._publish_diagnosis_event(
            {
                **event,
                "monitor_report": monitor_report,
                "error_snippet": error_snippet,
            }
        )

    async def _handle_diagnosis_event(self, event: dict[str, Any]) -> None:
        if event.get("event_type") != "workflow_run":
            return

        pipeline_run = await PipelineRun.get(PydanticObjectId(event["pipeline_run_id"]))
        if pipeline_run is None:
            return

        monitor_report = event.get("monitor_report") or {}
        if monitor_report.get("status") != "FAILURE":
            pipeline_run.diagnosis_status = "skipped"
            pipeline_run.updated_at = _now()
            await pipeline_run.save()
            return

        compare_diff = "Git diff unavailable."
        if event.get("installation_id") and event.get("repo"):
            try:
                compare_diff = await fetch_compare_diff(
                    installation_id=event["installation_id"],
                    repository_full_name=event["repo"],
                    base_sha=event.get("base_sha"),
                    head_sha=event.get("head_sha"),
                )
            except Exception as exc:
                compare_diff = f"Git diff lookup failed: {exc}"

        diagnosis_time = _iso(_now())
        system_prompt = (
            "Return only strict JSON with keys name, branch, error_type, possible_causes, latest_working_change."
        )
        user_prompt = (
            f"Monitor error log:\n{monitor_report.get('error', '') or event.get('error_snippet', '')}\n\n"
            f"Git diff:\n{compare_diff}"
        )

        try:
            response_text, provider, model = await call_with_fallback(
                primary_provider=settings.DIAGNOSIS_AGENT_PRIMARY_PROVIDER,
                primary_model=settings.DIAGNOSIS_AGENT_PRIMARY_MODEL,
                fallback_provider=settings.DIAGNOSIS_AGENT_FALLBACK_PROVIDER,
                fallback_model=settings.DIAGNOSIS_AGENT_FALLBACK_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
            diagnosis_report = _parse_json_object(
                response_text,
                {
                    "name": event.get("workflow_name") or "",
                    "branch": event.get("branch") or "",
                    "error_type": "Runtime Failure",
                    "possible_causes": ["Inspect the failing step and recent diff"],
                    "latest_working_change": f"{_first_diff_file(compare_diff)} {_first_change_summary(compare_diff)}".strip(),
                },
            )
            diagnosis_report["name"] = diagnosis_report.get("name") or event.get("workflow_name") or ""
            diagnosis_report["branch"] = diagnosis_report.get("branch") or event.get("branch") or ""
            pipeline_run.diagnosis_status = "completed"
            pipeline_run.diagnosis_report_json = diagnosis_report
            pipeline_run.diagnosis_report = json.dumps(diagnosis_report, separators=(",", ":"))
            pipeline_run.diagnosis_provider = provider
            pipeline_run.diagnosis_model = model
            pipeline_run.diagnosis_error = None
        except Exception as exc:
            pipeline_run.diagnosis_status = "failed"
            pipeline_run.diagnosis_error = str(exc)

        pipeline_run.updated_at = _now()
        await pipeline_run.save()


pipeline_runtime = PipelineRuntime()
