"""Formatação de respostas HTTP e resumos de execução da sincronização (View)."""


def health_view() -> dict[str, str]:
    """Formata a resposta de disponibilidade da aplicação."""
    return {"status": "ok"}


def report_view(items: list[dict], statuses: tuple[str, ...]) -> dict:
    """Formata o relatório padronizado (total, resumo por status e resultados)."""
    return {
        "total": len(items),
        "resumo": {s: sum(r["status"] == s for r in items) for s in statuses},
        "resultados": items,
    }


def accounts_report_view(results: list[dict], kind: str = "students") -> dict:
    """Formata o relatório de sincronização de contas de alunos ou professores."""
    collection_key = "alunos" if kind == "students" else "professores"
    return {
        "total": len(results),
        "resumo": {
            status: sum(r["status"] == status for r in results)
            for status in ("criado", "existente", "erro")
        },
        collection_key: results,
    }


def conflict_view(state: dict | None) -> dict:
    """Formata o payload de conflito HTTP 409 com o progresso atual."""
    current = state or {
        "operacao": None,
        "etapa": None,
        "concluidos": None,
        "total": None,
        "item": None,
    }
    return {"mensagem": "Uma sincronização já está em execução.", **current}


def summary_view(result: object) -> str:
    """Formata o resumo textual conciso para registro em log ao fim da execução."""
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
