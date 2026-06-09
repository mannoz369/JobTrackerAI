from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.backfill import router as backfill_router
from app.api.gmail import router as gmail_router
from app.api.pubsub import router as pubsub_router
from app.api.review import router as review_router
from app.core.config import Settings, get_settings
from app.db.mongo import close_mongo, configure_mongo
from app.repositories.backfill_jobs import BackfillJobsRepository
from app.repositories.applications import ApplicationsRepository
from app.repositories.companies import CompaniesRepository
from app.repositories.emails import EmailsRepository
from app.repositories.status_updates import StatusUpdatesRepository
from app.repositories.users import UsersRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        configure_mongo(app, resolved_settings)
        mongo_db = getattr(app.state, "mongo_db", None)
        if mongo_db is not None:
            await UsersRepository(mongo_db).ensure_indexes()
            await BackfillJobsRepository(mongo_db).ensure_indexes()
            await EmailsRepository(mongo_db).ensure_indexes()
            await CompaniesRepository(mongo_db).ensure_indexes()
            await ApplicationsRepository(mongo_db).ensure_indexes()
            await StatusUpdatesRepository(mongo_db).ensure_indexes()
        yield
        close_mongo(app)

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": resolved_settings.app_name,
            "environment": resolved_settings.environment,
        }

    app.include_router(auth_router)
    app.include_router(backfill_router)
    app.include_router(gmail_router)
    app.include_router(pubsub_router)
    app.include_router(applications_router)
    app.include_router(review_router)

    return app


app = create_app()
