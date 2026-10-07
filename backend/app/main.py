"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    application = FastAPI(title="IPS Generator API", version="0.1.0")
    application.include_router(health_router)
    return application


app = create_app()
