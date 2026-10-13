"""FastAPI application entry point.

``create_app()`` refuses to build an app with an unsafe configuration (no authentication outside
development, replay extractor outside development; see `app.services.check_runtime_config`).
Services (database, storage, Redis, queue) are created at start-up unless passed in (tests).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.config import Settings, get_settings
from app.services import Services, build_services, check_runtime_config


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    settings = settings or (services.settings if services else get_settings())
    check_runtime_config(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if getattr(application.state, "services", None) is None:
            logging.basicConfig(level=settings.log_level)
            application.state.services = build_services(settings)
        yield

    application = FastAPI(title="IPS Generator API", version="0.1.0", lifespan=lifespan)
    application.state.services = services
    install_error_handlers(application)

    @application.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            # API responses can carry PHI: never store them in any cache (D8).
            response.headers["Cache-Control"] = "no-store"
            response.headers.setdefault("Pragma", "no-cache")
        return response

    application.include_router(health_router)
    application.include_router(jobs_router)
    return application


app = create_app()
