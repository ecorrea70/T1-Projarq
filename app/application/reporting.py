"""Resumos compartilhados dos resultados de sincronização."""


def report(items, statuses):
    return {"total": len(items), "resumo": {s: sum(r["status"] == s for r in items) for s in statuses},
            "resultados": items}
