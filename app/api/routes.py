from typing import Annotated

from fastapi import APIRouter, Header

from app.application.synchronization.orchestrator import synchronize
from app.controllers.sync_controller import SyncController
from app.core.config import ConfigurationError, Settings
from app.infrastructure.clients.ieducar import IEducarClient
from app.infrastructure.clients.moodle import MoodleClient
from app.views.sync_view import conflict_view as conflict, summary_view as summary


router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    """Indica que a aplicação está disponível."""
    return SyncController().health()


@router.post("/sync/students")
def sync_students(authorization: Annotated[str | None, Header()] = None):
    return run_sync(authorization, "students")


@router.post("/sync/teachers")
def sync_teachers(authorization: Annotated[str | None, Header()] = None):
    return run_sync(authorization, "teachers")


def run_sync(authorization: str | None, kind: str):
    controller = SyncController(
        source_factory=IEducarClient,
        destination_factory=MoodleClient,
        sync_runner=synchronize,
        settings_loader=Settings.from_env,
    )
    return controller.handle_sync(authorization, kind)


__all__ = ["router", "healthcheck", "sync_students", "sync_teachers", "run_sync", "conflict", "summary", "ConfigurationError"]
