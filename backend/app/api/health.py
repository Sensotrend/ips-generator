"""Liveness endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


@router.get("/health")
def health() -> HealthResponse:
    """Return OK when the API process is up."""
    return HealthResponse(status="ok")
