import fcntl
import os
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from app.infrastructure.clients.ieducar import IEducarClient
from app.infrastructure.clients.moodle import MoodleClient
from app.core.errors import IntegrationError
from app.core.config import ConfigurationError, Settings
from app.core.log import logger
from app.core.progress import progress
from app.application.synchronization.orchestrator import synchronize


router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    """Indica que a aplicação está disponível."""
    return {"status": "ok"}


@router.post("/sync/students")
def sync_students(authorization: Annotated[str | None, Header()] = None):
    return run_sync(authorization, "students")


@router.post("/sync/teachers")
def sync_teachers(authorization: Annotated[str | None, Header()] = None):
    return run_sync(authorization, "teachers")


def run_sync(authorization, kind):
    token = os.getenv("SYNC_API_TOKEN", "")
    if not token:
        raise HTTPException(503, "Configure SYNC_API_TOKEN.")
    if not authorization or not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Token de sincronização inválido.")
    try:
        settings = Settings.from_env(kind)
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from None
    label = "alunos" if kind == "students" else "professores"
    log = logger()
    # Lock entre processos/workers no mesmo container. Um único container
    # deve executar a sincronização, conforme a arquitetura monolítica.
    with open("/tmp/t1-monolith-students.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            state = progress.snapshot()
            log.warning("Sincronização de %s recusada. Em execução: %s", label, state)
            raise HTTPException(409, conflict(state)) from None
        started = time.perf_counter()
        generation = progress.start(kind)
        log.info("Sincronização de %s iniciada.", label)
        try:
            result = synchronize(IEducarClient(settings), MoodleClient(settings), kind)
            log.info("Sincronização de %s concluída em %.1fs. %s", label, time.perf_counter() - started, summary(result))
            return result
        except IntegrationError as exc:
            log.error("Sincronização de %s falhou em %.1fs: %s", label, time.perf_counter() - started, exc)
            raise HTTPException(502, str(exc)) from None
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            progress.finish(generation)


def conflict(state):
    current = state or {"operacao": None, "etapa": None, "concluidos": None, "total": None, "item": None}
    return {"mensagem": "Uma sincronização já está em execução.", **current}


def summary(result):
    if not isinstance(result, dict):
        return ""
    parts = []
    if isinstance(result.get("resumo"), dict):
        parts.append(f"contas={result['resumo']}")
    for key in ("cursos", "vinculos"):
        value = result.get(key)
        if isinstance(value, dict) and isinstance(value.get("resumo"), dict):
            parts.append(f"{key}={value['resumo']}")
    return " ".join(parts)
