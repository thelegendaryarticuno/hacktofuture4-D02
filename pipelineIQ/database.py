"""
MongoDB connection lifecycle using motor (async) + beanie (ODM).
"""

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from config import settings
from models.user import User
from models.workspace import Workspace
from models.repository import Repository
from models.webhook_event import WebhookEvent

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    """Initialise the MongoDB connection and Beanie document models."""
    global _client
    _client = AsyncIOMotorClient(settings.MONGODB_URI)
    await init_beanie(
        database=_client[settings.MONGODB_DB_NAME],
        document_models=[User, Workspace, Repository, WebhookEvent],
    )


async def disconnect_db() -> None:
    """Gracefully close the MongoDB connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
