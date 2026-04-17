from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from config import settings
from models.autofix_execution import AutoFixExecution
from models.autofix_feedback import AutoFixFeedback
from models.autofix_memory import AutoFixMemory
from models.pipeline_run import PipelineRun
from models.repository import Repository
from models.user import User
from models.webhook_event import WebhookEvent
from models.workspace import Workspace

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.MONGODB_URI)
    await init_beanie(
        database=_client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Workspace,
            Repository,
            WebhookEvent,
            PipelineRun,
            AutoFixExecution,
            AutoFixFeedback,
            AutoFixMemory,
        ],
    )


async def disconnect_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
