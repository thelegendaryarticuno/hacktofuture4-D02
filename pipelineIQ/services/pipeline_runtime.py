from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from beanie import PydanticObjectId

from config import settings
from models.pipeline_run import PipelineRun
from models.workspace import Workspace
from services.github_app import download_workflow_logs, fetch_compare_diff
from services.llm_gateway import call_with_fallback

logger = logging.getLogger(__name__)

SUPPORTED_PIPELINE_EVENTS = {"workflow_run"}
SUPPORTED_WORKFLOW_ACTIONS = {"requested", "in_progress", "completed"}
BUILD_DEPLOY_KEYWORDS = (
    "build",
    "deploy",
    "deployment",
    "release",
    "publish",
    "artifact",
    "docker",
    "image",
    "helm",
    "k8s",
)
TRACKED_STEPS = ["build", "test", "deploy"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _health_from_conclusion(conclusion: str | None) -> str:
    normalized = (conclusion or "").lower()
    if normalized in {"success", "completed"}:
        return "healthy"
    if normalized in {"failure", "timed_out", "startup_failure", "action_required"}:
        return "failing"
    if normalized in {"cancelled", "neutral", "skipped"}:
        return "degraded"
    return "unknown"


def build_pipeline_event(
    workspace: Workspace,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str,
) -> dict[str, Any]:
    workflow_run = payload.get("workflow_run") or {}
    repository = payload.get("repository") or {}

    run_id = None
    workflow_name = None
    workflow_url = None
    branch = None
    commit_sha = None
    conclusion = None
    triggered_by = payload.get("action") or event_type
    workflow_status = None
    base_sha = None
    run_started_at = None
    run_updated_at = None

    if event_type == "workflow_run":
        run_id = workflow_run.get("id")
        workflow_name = workflow_run.get("name") or payload.get("workflow", {}).get("name")
        workflow_url = workflow_run.get("html_url")
        branch = workflow_run.get("head_branch")
        commit_sha = workflow_run.get("head_sha")
        workflow_status = workflow_run.get("status")
        conclusion = workflow_run.get("conclusion") or workflow_status
        triggered_by = workflow_run.get("event") or payload.get("action") or event_type
        run_started_at = workflow_run.get("run_started_at") or workflow_run.get("created_at")
        run_updated_at = workflow_run.get("updated_at")

        pull_requests = workflow_run.get("pull_requests") or []
        if pull_requests:
            base_sha = (pull_requests[0].get("base") or {}).get("sha")

        if not base_sha:
            head_commit = workflow_run.get("head_commit") or {}
            parent_commits = head_commit.get("parents") or []
            if parent_commits:
                base_sha = parent_commits[0].get("sha")

    repo_full_name = (
        repository.get("full_name")
        or workspace.github_repo_full_name
        or "unknown/unknown"
    )

    return {
        "pipeline_run_id": None,
        "workspace_id": str(workspace.id),
        "installation_id": workspace.github_installation_id,
        "delivery_id": delivery_id,
        "repo": repo_full_name,
        "run_id": run_id,
        "workflow_name": workflow_name,
        "workflow_url": workflow_url,
        "workflow_status": workflow_status,
        "conclusion": conclusion,
        "branch": branch,
        "commit_sha": commit_sha,
        "base_sha": base_sha,
        "run_started_at": run_started_at,
        "run_updated_at": run_updated_at,
        "triggered_by": triggered_by,
        "event_type": event_type,
        "action": payload.get("action"),
        "health_status": _health_from_conclusion(conclusion),
    }


def should_process_pipeline_event(event_type: str, payload: dict[str, Any]) -> bool:
    if event_type not in SUPPORTED_PIPELINE_EVENTS:
        return False

    action = (payload.get("action") or "").lower()
    if action and action not in SUPPORTED_WORKFLOW_ACTIONS:
        return False

    workflow_run = payload.get("workflow_run") or {}
    if workflow_run.get("id") is None:
        return False

    status = (workflow_run.get("status") or "").lower()
    if status not in {"queued", "in_progress", "completed", "requested"}:
        return False

    return True


def _is_workflow_event_record(event: dict[str, Any]) -> bool:
    return event.get("event_type") == "workflow_run"


def _extract_build_deploy_logs(logs_text: str) -> tuple[str, list[str]]:
    if not logs_text:
        return "", []

    lines = logs_text.splitlines()
    selected_indexes: set[int] = set()

    for index, line in enumerate(lines):
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in BUILD_DEPLOY_KEYWORDS):
            for cursor in (index - 1, index, index + 1):
                if 0 <= cursor < len(lines):
                    selected_indexes.add(cursor)

    if not selected_indexes:
        return "", []

    filtered_lines = [
        lines[index].strip()
        for index in sorted(selected_indexes)
        if lines[index].strip()
    ]
    filtered_lines = filtered_lines[:300]
    return "\n".join(filtered_lines), filtered_lines[:40]


def _serialize_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _safe_parse_dt(value: Any) -> datetime | None:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_string(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return ""
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        seconds = 0
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _classify_error(logs_text: str, conclusion: str | None) -> dict[str, Any]:
    text = (logs_text or "").lower()
    lines = [line.strip() for line in (logs_text or "").splitlines() if line.strip()]

    patterns = [
        ("Dependency Error", ["dependency", "module not found", "could not resolve", "lockfile", "npm err", "pip error"]),
        ("Build Error", ["build failed", "compile error", "compilation failed", "syntax error", "ts error"]),
        ("Test Failure", ["test failed", "assertion", "failing test", "pytest", "jest"]),
        ("Deployment Error", ["deploy failed", "rollout failed", "helm", "kubectl", "permission denied", "image pull"]),
        ("Timeout", ["timed out", "timeout", "deadline exceeded"]),
    ]

    for error_type, keywords in patterns:
        if any(keyword in text for keyword in keywords):
            evidence_line = next((line for line in lines if any(keyword in line.lower() for keyword in keywords)), "")
            return {
                "exists": True,
                "type": error_type,
                "message": evidence_line or f"Detected {error_type.lower()} from workflow logs.",
            }

    if (conclusion or "").lower() in {"failure", "timed_out", "startup_failure", "cancelled"}:
        fallback_line = next((line for line in lines if "error" in line.lower() or "failed" in line.lower()), "Workflow finished with failure but no explicit error line was found.")
        return {
            "exists": True,
            "type": "Workflow Failure",
            "message": fallback_line,
        }

    return {
        "exists": False,
        "type": "",
        "message": "",
    }


def _derive_step_state(
    previous_report: dict[str, Any] | None,
    filtered_logs_text: str,
    workflow_status: str | None,
    conclusion: str | None,
) -> tuple[str, list[str], list[str]]:
    previous_completed = [
        step
        for step in (previous_report or {}).get("steps_completed", [])
        if step in TRACKED_STEPS
    ]
    completed = list(dict.fromkeys(previous_completed))
    text = (filtered_logs_text or "").lower()

    success_hints = {
        "build": ["build success", "build completed", "compile success", "artifact uploaded"],
        "test": ["tests passed", "test success", "all tests passed"],
        "deploy": ["deployment successful", "deploy success", "rollout complete", "release successful"],
    }

    for step, hints in success_hints.items():
        if any(hint in text for hint in hints) and step not in completed:
            completed.append(step)

    if (workflow_status or "").lower() == "completed" and (conclusion or "").lower() == "success":
        for step in ["build", "deploy"]:
            if step not in completed:
                completed.append(step)

    current_step = ""
    if (workflow_status or "").lower() != "completed":
        if "deploy" in text and "deploy" not in completed:
            current_step = "deploy"
        elif "test" in text and "test" not in completed:
            current_step = "test"
        elif "build" not in completed:
            current_step = "build"
        elif "test" not in completed and "test" in text:
            current_step = "test"
        elif "deploy" not in completed:
            current_step = "deploy"

    pending = [step for step in TRACKED_STEPS if step not in completed and step != current_step]
    return current_step, completed, pending


def _normalize_monitor_report(
    workflow_id: str,
    previous_report: dict[str, Any] | None,
    llm_report: dict[str, Any],
    *,
    workflow_status: str | None,
    conclusion: str | None,
    now: datetime,
    run_started_at: datetime | None,
    run_updated_at: datetime | None,
    filtered_logs_text: str,
) -> dict[str, Any]:
    start_time = _safe_parse_dt((previous_report or {}).get("start_time")) or run_started_at or now
    last_updated = run_updated_at or now

    current_step, completed, pending = _derive_step_state(
        previous_report,
        filtered_logs_text,
        workflow_status,
        conclusion,
    )

    status = "RUNNING"
    end_time = None
    if (workflow_status or "").lower() == "completed":
        normalized_conclusion = (conclusion or "").lower()
        if normalized_conclusion == "success":
            status = "SUCCESS"
        else:
            status = "FAILURE"
        end_time = last_updated

    error_info = _classify_error(filtered_logs_text, conclusion)
    if status == "SUCCESS":
        error_info = {"exists": False, "type": "", "message": ""}

    if status == "RUNNING" and llm_report.get("error", {}).get("exists") is True:
        error_info = llm_report.get("error")

    duration = _duration_string(start_time, end_time or last_updated)

    return {
        "workflow_id": workflow_id,
        "status": status,
        "start_time": _serialize_dt(start_time),
        "last_updated": _serialize_dt(last_updated),
        "end_time": _serialize_dt(end_time),
        "duration": duration,
        "current_step": current_step,
        "steps_completed": completed,
        "steps_pending": pending,
        "error": {
            "exists": bool(error_info.get("exists")),
            "type": error_info.get("type", ""),
            "message": error_info.get("message", ""),
        },
    }


def _monitor_schema_fallback(workflow_id: str) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "status": "RUNNING",
        "start_time": "",
        "last_updated": "",
        "end_time": "",
        "duration": "",
        "current_step": "",
        "steps_completed": [],
        "steps_pending": ["build", "test", "deploy"],
        "error": {
            "exists": False,
            "type": "",
            "message": "",
        },
    }


def _parse_json_object(raw_response: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    json_match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {
        **fallback,
        "raw_response": raw_response,
        "parsing_error": "Agent response was not valid JSON.",
    }


class PipelineRuntime:
    def __init__(self) -> None:
        self.producer: AIOKafkaProducer | None = None
        self.monitor_consumer: AIOKafkaConsumer | None = None
        self.diagnosis_consumer: AIOKafkaConsumer | None = None
        self.tasks: list[asyncio.Task] = []
        self.started = False
        self.workflow_state_store: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        if self.started:
            return
        if not settings.KAFKA_ENABLED:
            logger.info("Kafka disabled; using direct in-process pipeline processing.")
            self.started = True
            return

        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
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
            asyncio.create_task(
                self._consume_loop(self.monitor_consumer, self._handle_monitor_event),
                name="pipelineiq-monitor-consumer",
            ),
            asyncio.create_task(
                self._consume_loop(
                    self.diagnosis_consumer,
                    self._handle_diagnosis_event,
                ),
                name="pipelineiq-diagnosis-consumer",
            ),
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
        workflow_id = str(event.get("run_id") or "")

        if event_type == "workflow_run" and event.get("run_id") is not None:
            existing_run = await PipelineRun.find_one(
                PipelineRun.workspace_id == workspace.id,
                PipelineRun.event_type == "workflow_run",
                PipelineRun.run_id == event["run_id"],
            )
            if existing_run is not None:
                existing_run.delivery_id = delivery_id
                existing_run.action = event.get("action")
                existing_run.workflow_status = event.get("workflow_status")
                existing_run.conclusion = event.get("conclusion")
                existing_run.health_status = event.get("health_status")
                existing_run.branch = event.get("branch")
                existing_run.commit_sha = event.get("commit_sha")
                existing_run.triggered_by = event.get("triggered_by")
                existing_run.raw_event = payload
                existing_run.updated_at = _now()
                await existing_run.save()

                event["pipeline_run_id"] = str(existing_run.id)
                await self._publish_pipeline_event(event)
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
            workflow_url=event["workflow_url"],
            workflow_status=event["workflow_status"],
            branch=event["branch"],
            commit_sha=event["commit_sha"],
            triggered_by=event["triggered_by"],
            conclusion=event["conclusion"],
            health_status=event["health_status"],
            raw_event=payload,
            monitor_report_json=_monitor_schema_fallback(workflow_id),
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

    async def _consume_loop(
        self,
        consumer: AIOKafkaConsumer,
        handler,
    ) -> None:
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
        if not _is_workflow_event_record(event):
            logger.info("Skipping non-workflow event in monitor consumer")
            return

        pipeline_run = await PipelineRun.get(PydanticObjectId(event["pipeline_run_id"]))
        if pipeline_run is None:
            return

        logs_text = ""
        if (
            event.get("run_id")
            and event.get("installation_id")
            and event.get("repo")
        ):
            try:
                logs_text = await download_workflow_logs(
                    installation_id=event["installation_id"],
                    repository_full_name=event["repo"],
                    run_id=event["run_id"],
                )
            except Exception as exc:
                logs_text = f"Failed to fetch workflow logs: {exc}"

        filtered_logs_text, excerpt_lines = _extract_build_deploy_logs(logs_text)
        excerpt = filtered_logs_text[:12000]
        workflow_id = str(event.get("run_id") or pipeline_run.run_id or "")
        previous_report = self.workflow_state_store.get(workflow_id) or pipeline_run.monitor_report_json or {}
        run_started_at = _safe_parse_dt(event.get("run_started_at"))
        run_updated_at = _safe_parse_dt(event.get("run_updated_at"))

        system_prompt = (
            "You are the PipelineIQ Monitor Agent. "
            "Return ONLY strict JSON and no markdown. "
            "Schema: "
            "{"
            '"workflow_id":"string",'
            '"status":"RUNNING|SUCCESS|FAILURE",'
            '"start_time":"ISO-8601",'
            '"last_updated":"ISO-8601",'
            '"end_time":"ISO-8601 or empty",'
            '"duration":"HH:MM:SS",'
            '"current_step":"build|test|deploy|empty",'
            '"steps_completed":["build|test|deploy"],'
            '"steps_pending":["build|test|deploy"],'
            '"error":{"exists":true|false,"type":"string","message":"string"}'
            "}."
        )
        user_prompt = (
            f"Pipeline event:\n{json.dumps(event, indent=2)}\n\n"
            f"Previous monitor report:\n{json.dumps(previous_report, indent=2)}\n\n"
            "Use ONLY build/deployment-related logs below. Ignore unrelated lines.\n\n"
            f"Filtered workflow logs:\n{excerpt or 'No build/deployment logs were available for this workflow run.'}"
        )
        try:
            response_text, provider, model = await call_with_fallback(
                primary_provider=settings.MONITOR_AGENT_PRIMARY_PROVIDER,
                primary_model=settings.MONITOR_AGENT_PRIMARY_MODEL,
                fallback_provider=settings.MONITOR_AGENT_FALLBACK_PROVIDER,
                fallback_model=settings.MONITOR_AGENT_FALLBACK_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
        except Exception as exc:
            pipeline_run.monitor_status = "failed"
            pipeline_run.monitor_summary = f"Monitor agent failed: {exc}"
            fallback_report = _monitor_schema_fallback(workflow_id)
            fallback_report["error"] = {
                "exists": True,
                "type": "Monitor Error",
                "message": pipeline_run.monitor_summary,
            }
            pipeline_run.monitor_report_json = fallback_report
            pipeline_run.monitor_logs_excerpt = excerpt_lines
            pipeline_run.error_summary = pipeline_run.monitor_summary
            pipeline_run.updated_at = _now()
            await pipeline_run.save()
            return

        llm_report = _parse_json_object(
            response_text,
            _monitor_schema_fallback(workflow_id),
        )
        monitor_report = _normalize_monitor_report(
            workflow_id,
            previous_report,
            llm_report,
            workflow_status=event.get("workflow_status"),
            conclusion=event.get("conclusion"),
            now=_now(),
            run_started_at=run_started_at,
            run_updated_at=run_updated_at,
            filtered_logs_text=filtered_logs_text,
        )
        self.workflow_state_store[workflow_id] = monitor_report

        pipeline_run.monitor_status = "completed"
        pipeline_run.monitor_summary = (
            f"{monitor_report.get('status', 'RUNNING')} - "
            f"current step: {monitor_report.get('current_step') or 'n/a'}"
        )
        pipeline_run.monitor_report_json = monitor_report
        pipeline_run.monitor_logs_excerpt = excerpt_lines
        pipeline_run.monitor_provider = provider
        pipeline_run.monitor_model = model
        pipeline_run.workflow_status = event.get("workflow_status")
        if monitor_report.get("status") == "SUCCESS":
            pipeline_run.health_status = "healthy"
        elif monitor_report.get("status") == "FAILURE":
            pipeline_run.health_status = "failing"
        else:
            pipeline_run.health_status = "unknown"
        pipeline_run.enriched_event = {
            "raw_logs_excerpt": (logs_text or "")[:12000],
            "logs_excerpt": excerpt,
            "monitor_summary": pipeline_run.monitor_summary,
            "monitor_report": monitor_report,
        }
        pipeline_run.updated_at = _now()

        if monitor_report.get("status") != "FAILURE" or not monitor_report.get("error", {}).get("exists"):
            pipeline_run.diagnosis_status = "skipped"
            await pipeline_run.save()
            return

        if pipeline_run.diagnosis_status in {"queued", "completed"}:
            await pipeline_run.save()
            return

        pipeline_run.diagnosis_status = "queued"
        pipeline_run.error_summary = monitor_report.get("error", {}).get("message") or pipeline_run.monitor_summary
        await pipeline_run.save()

        enriched_event = {
            **event,
            "raw_logs_excerpt": (logs_text or "")[:12000],
            "logs_excerpt": excerpt,
            "monitor_summary": pipeline_run.monitor_summary,
            "monitor_report": monitor_report,
        }
        await self._publish_diagnosis_event(enriched_event)

    async def _handle_diagnosis_event(self, event: dict[str, Any]) -> None:
        if not _is_workflow_event_record(event):
            logger.info("Skipping non-workflow event in diagnosis consumer")
            return

        pipeline_run = await PipelineRun.get(PydanticObjectId(event["pipeline_run_id"]))
        if pipeline_run is None:
            return

        monitor_report = event.get("monitor_report") or {}
        if not monitor_report.get("error", {}).get("exists"):
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
                    head_sha=event.get("commit_sha"),
                )
            except Exception as exc:
                compare_diff = f"Git diff lookup failed: {exc}"

        diagnosis_time = _now().isoformat()
        system_prompt = (
            "You are the PipelineIQ Diagnosis Agent. "
            "Return ONLY a strict JSON object with no markdown, headings, or code fences. "
            "Use this schema: "
            "{"
            '"workflow_id":"string",'
            '"error_type":"string",'
            '"root_cause":"string",'
            '"trigger_change":"string",'
            '"before_state":"string",'
            '"after_state":"string",'
            '"impact":"string",'
            '"suggested_fix":"string",'
            '"severity":"LOW|MEDIUM|HIGH",'
            '"diagnosis_time":"ISO-8601"'
            "}."
        )
        user_prompt = (
            f"Pipeline event:\n{json.dumps(event, indent=2)}\n\n"
            f"Monitor report:\n{json.dumps(monitor_report, indent=2)}\n\n"
            f"Raw workflow logs:\n{event.get('raw_logs_excerpt', 'No workflow logs available.')}\n\n"
            f"Git diff (before vs after):\n{compare_diff}\n\n"
            f"Diagnosis generation time: {diagnosis_time}"
        )
        try:
            response_text, provider, model = await call_with_fallback(
                primary_provider=settings.DIAGNOSIS_AGENT_PRIMARY_PROVIDER,
                primary_model=settings.DIAGNOSIS_AGENT_PRIMARY_MODEL,
                fallback_provider=settings.DIAGNOSIS_AGENT_FALLBACK_PROVIDER,
                fallback_model=settings.DIAGNOSIS_AGENT_FALLBACK_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.15,
            )
            diagnosis_report = _parse_json_object(
                response_text,
                {
                    "workflow_id": str(event.get("run_id") or pipeline_run.run_id or ""),
                    "error_type": monitor_report.get("error", {}).get("type", "Workflow Failure"),
                    "root_cause": "Diagnosis parsing fallback.",
                    "trigger_change": "Unable to parse trigger change.",
                    "before_state": "Workflow was previously passing.",
                    "after_state": "Workflow is now failing.",
                    "impact": "Pipeline execution blocked.",
                    "suggested_fix": "Inspect error log details and recent code changes.",
                    "severity": "MEDIUM",
                    "diagnosis_time": diagnosis_time,
                },
            )
            diagnosis_report["workflow_id"] = str(event.get("run_id") or diagnosis_report.get("workflow_id") or "")
            diagnosis_report["diagnosis_time"] = diagnosis_report.get("diagnosis_time") or diagnosis_time
            pipeline_run.diagnosis_status = "completed"
            pipeline_run.diagnosis_report_json = diagnosis_report
            pipeline_run.diagnosis_report = json.dumps(diagnosis_report, indent=2)
            pipeline_run.diagnosis_provider = provider
            pipeline_run.diagnosis_model = model
            pipeline_run.diagnosis_error = None
        except Exception as exc:
            pipeline_run.diagnosis_status = "failed"
            pipeline_run.diagnosis_error = str(exc)

        pipeline_run.updated_at = _now()
        await pipeline_run.save()


pipeline_runtime = PipelineRuntime()
