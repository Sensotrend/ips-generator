"""Request dependencies: services and the current user.

Authentication is deferred (PLAN Phase 3 OIDC): in development a fixed reviewer identity is
returned. OIDC slots in by replacing `get_current_user` (validate the bearer token, map claims
to `CurrentUser`); the routes only depend on it. `app.services.check_runtime_config` refuses to
start outside development until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.api.errors import ApiError
from app.config import AuthMode
from app.services import Services

__all__ = ["CurrentUser", "CurrentUserDep", "ServicesDep", "get_current_user", "get_services"]

DEV_REVIEWER_ID = "dev-reviewer"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    display_name: str


def get_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise ApiError(503, "not_ready", "The service is starting.")
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_current_user(services: ServicesDep) -> CurrentUser:
    settings = services.settings
    if settings.auth_mode is AuthMode.DEV and settings.is_development:
        return CurrentUser(id=DEV_REVIEWER_ID, display_name=settings.dev_reviewer_name)
    raise ApiError(401, "unauthenticated", "Authentication is required.")


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
