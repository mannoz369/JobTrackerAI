from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import Settings


def configure_mongo(app, settings: Settings) -> None:
    if settings.mongodb_uri is None:
        app.state.mongo_client = None
        app.state.mongo_db = None
        return

    client = AsyncIOMotorClient(settings.mongodb_uri)
    app.state.mongo_client = client
    app.state.mongo_db = client[settings.mongodb_database]


def close_mongo(app) -> None:
    client: AsyncIOMotorClient | None = getattr(app.state, "mongo_client", None)
    if client is not None:
        client.close()


def get_mongo_database(request: Request) -> AsyncIOMotorDatabase:
    database: AsyncIOMotorDatabase | None = getattr(request.app.state, "mongo_db", None)
    if database is None:
        raise RuntimeError(
            "MongoDB is not configured. Set MONGODB_URI and MONGODB_DATABASE."
        )
    return database
