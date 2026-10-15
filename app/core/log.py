"""Log de progresso da sincronização, visível em `docker compose logs api`."""
import logging
import sys


def logger():
    log = logging.getLogger("sync")
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [sync] %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


def failure(exc):
    if hasattr(exc, "code") and hasattr(exc, "reason"):
        return f"HTTP {exc.code} {exc.reason}"
    reason = getattr(exc, "reason", exc)
    return f"{type(exc).__name__}: {reason}"
