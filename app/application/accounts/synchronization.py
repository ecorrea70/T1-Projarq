"""Consulta, prevenção de conflitos e criação de contas de ambos os perfis."""
from app.application.accounts.mapping import map_identity, map_user
from app.core.errors import IntegrationError
from app.core.log import logger
from app.core.progress import progress


def synchronize_users(people, destination, kind="students"):
    label = "aluno" if kind == "students" else "professor"
    log = logger()
    results = []
    total = len(people)
    for index, person in enumerate(people, start=1):
        person_id = person.get(f"{label}_id")
        progress.advance("Sincronizando contas", index - 1, total, f"{label} {person_id}")
        log.info("Conta %s %d/%d id=%s.", label, index, total, person_id)
        item = {f"{label}_id": person_id}
        try:
            if person.get("erro_origem"):
                raise IntegrationError(person["erro_origem"])
            # Identidade é verificada antes do e-mail: contas já sincronizadas
            # continuam reconhecidas mesmo se o cadastro depois ficar incompleto.
            identity = map_identity(person, kind)["idnumber"]
            existing = destination.find("idnumber", identity)
            if len(existing) > 1:
                raise ValueError(f"Mais de uma conta possui a identidade do {label}.")
            if existing:
                item.update(status="existente", moodle_id=existing[0]["id"])
            else:
                user = map_user(person, kind)
                if destination.find("username", user["username"]):
                    raise ValueError("Login ocupado por uma conta sem o vínculo esperado.")
                if destination.find("email", user["email"]):
                    raise ValueError("E-mail já utilizado por outra conta no Moodle.")
                item.update(status="criado", moodle_id=destination.create(user))
        except (ValueError, IntegrationError) as exc:
            item.update(status="erro", mensagem=str(exc))
        log.info("Conta %s %d/%d id=%s: %s.", label, index, total, person_id, item["status"])
        progress.advance("Sincronizando contas", index, total, f"{label} {person_id}: {item['status']}")
        results.append(item)
    return {"total": len(results),
            "resumo": {status: sum(r["status"] == status for r in results)
                       for status in ("criado", "existente", "erro")},
            "alunos" if kind == "students" else "professores": results}
