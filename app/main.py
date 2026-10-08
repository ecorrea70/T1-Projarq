import fcntl
import os
import secrets
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.clients import IEducarClient, IntegrationError, MoodleClient
from app.config import ConfigurationError, Settings
from app.sync import synchronize

app = FastAPI(title="T1 Monolith")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    """Indica que a aplicação está disponível."""
    return {"status": "ok"}


class SyncRequest(BaseModel):
    dry_run: bool = True


@app.post("/sync/students")
def sync_students(body: SyncRequest, authorization: Annotated[str | None, Header()] = None):
    return run_sync(body, authorization, "students")


@app.post("/sync/teachers")
def sync_teachers(body: SyncRequest, authorization: Annotated[str | None, Header()] = None):
    return run_sync(body, authorization, "teachers")


def run_sync(body, authorization, kind):
    token = os.getenv("SYNC_API_TOKEN", "")
    if not token:
        raise HTTPException(503, "Configure SYNC_API_TOKEN.")
    if not authorization or not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Token de sincronização inválido.")
    try:
        settings = Settings.from_env(kind)
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from None
    # Lock entre processos/workers no mesmo container. Um único container
    # deve executar a sincronização, conforme a arquitetura monolítica.
    with open("/tmp/t1-monolith-students.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(409, "Uma sincronização já está em execução.") from None
        try:
            return synchronize(IEducarClient(settings), MoodleClient(settings), body.dry_run, kind)
        except IntegrationError as exc:
            raise HTTPException(502, str(exc)) from None
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
