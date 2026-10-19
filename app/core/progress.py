"""Estado da sincronização em andamento, lido pelo conflito 409."""
import threading

_KEEP = object()


class SyncProgress:
    def __init__(self):
        self._guard = threading.Lock()
        self._generation = 0
        self._state = None

    def start(self, kind):
        with self._guard:
            self._generation += 1
            generation = self._generation
            self._state = {
                "operacao": "alunos" if kind == "students" else "professores",
                "etapa": "Iniciando",
                "concluidos": 0,
                "total": None,
                "item": None,
            }
            return generation

    def advance(self, etapa, concluidos=_KEEP, total=_KEEP, item=_KEEP):
        with self._guard:
            if self._state is None:
                return
            self._state["etapa"] = etapa
            if concluidos is not _KEEP:
                self._state["concluidos"] = concluidos
            if total is not _KEEP:
                self._state["total"] = total
            if item is not _KEEP:
                self._state["item"] = item

    def snapshot(self):
        with self._guard:
            if self._state is None:
                return None
            return dict(self._state)

    def finish(self, generation):
        with self._guard:
            if generation == self._generation:
                self._state = None


progress = SyncProgress()
