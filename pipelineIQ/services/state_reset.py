from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient

from config import settings
from services.pipeline_runtime import pipeline_runtime


async def clear_backend_state() -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    try:
        database = client[settings.MONGODB_DB_NAME]
        for collection_name in (
            "users",
            "workspaces",
            "repositories",
            "webhook_events",
            "pipeline_runs",
            "autofix_executions",
            "autofix_feedbacks",
            "autofix_memories",
        ):
            await database[collection_name].delete_many({})
    finally:
        client.close()


def clear_runtime_state() -> None:
    pipeline_runtime.reset_state()
