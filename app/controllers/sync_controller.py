"""Controlador de sincronização: gerencia autenticação, lock exclusivo e despacho para a aplicação."""
import fcntl
import os
import secrets
import time
from typing import Callable

from fastapi import HTTPException

from app.application.contracts import StudentSource, UserDestination
from app.application.synchronization.orchestrator import synchronize
from app.core.config import ConfigurationError, Settings
from app.core.errors import IntegrationError
from app.core.log import logger
from app.core.progress import progress
from app.infrastructure.clients.ieducar import IEducarClient
from app.infrastructure.clients.moodle import MoodleClient
from app.views.sync_view import conflict_view, health_view, summary_view

LOCK_FILE_PATH = "/tmp/t1-monolith-students.lock"


class SyncAuthGuard:
    """Responsabilidade única (SRP): validar o token Bearer de sincronização."""

    @staticmethod
    def verify(authorization: str | None) -> None:
        token = os.getenv("SYNC_API_TOKEN", "")
        if not token:
            raise HTTPException(503, "Configure SYNC_API_TOKEN.")
        if not authorization or not secrets.compare_digest(
            authorization.encode(), f"Bearer {token}".encode()
        ):
            raise HTTPException(401, "Token de sincronização inválido.")


class SyncExecutionLock:
    """Responsabilidade única (SRP): garantir exclusão mútua entre processos no container."""

    def __init__(self, path: str = LOCK_FILE_PATH):
        self.path = path
        self._handle = None

    def __enter__(self):
        self._handle = open(self.path, "a")
        try:
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._handle is not None:
            try:
                fcntl.flock(self._handle, fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


class SyncController:
    """Controller (MVC): coordena requisição, segurança, concorrência, execução e View."""

    def __init__(
        self,
        source_factory: Callable[[Settings], StudentSource] = IEducarClient,
        destination_factory: Callable[[Settings], UserDestination] = MoodleClient,
        sync_runner: Callable[[StudentSource, UserDestination, str], dict] = synchronize,
        settings_loader: Callable[[str], Settings] = Settings.from_env,
    ):
        self.source_factory = source_factory
        self.destination_factory = destination_factory
        self.sync_runner = sync_runner
        self.settings_loader = settings_loader

    def health(self) -> dict[str, str]:
        return health_view()

    def handle_sync(self, authorization: str | None, kind: str) -> dict:
        SyncAuthGuard.verify(authorization)
        try:
            settings = self.settings_loader(kind)
        except ConfigurationError as exc:
            raise HTTPException(503, str(exc)) from None

        label = "alunos" if kind == "students" else "professores"
        log = logger()
        try:
            with SyncExecutionLock():
                started = time.perf_counter()
                generation = progress.start(kind)
                log.info("Sincronização de %s iniciada.", label)
                try:
                    source = self.source_factory(settings)
                    destination = self.destination_factory(settings)
                    result = self.sync_runner(source, destination, kind)
                    log.info(
                        "Sincronização de %s concluída em %.1fs. %s",
                        label,
                        time.perf_counter() - started,
                        summary_view(result),
                    )
                    return result
                except IntegrationError as exc:
                    log.error(
                        "Sincronização de %s falhou em %.1fs: %s",
                        label,
                        time.perf_counter() - started,
                        exc,
                    )
                    raise HTTPException(502, str(exc)) from None
                finally:
                    progress.finish(generation)
        except BlockingIOError:
            state = progress.snapshot()
            log.warning("Sincronização de %s recusada. Em execução: %s", label, state)
            raise HTTPException(409, conflict_view(state)) from None
