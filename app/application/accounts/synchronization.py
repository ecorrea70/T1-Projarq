"""Consulta, prevenção de conflitos e criação de contas de ambos os perfis."""
from app.application.accounts.mapping import map_identity, map_user
from app.core.errors import IntegrationError


def synchronize_users(people, destination, dry_run, kind="students"):
    label = "aluno" if kind == "students" else "professor"
    results = []
    for person in people:
        item = {f"{label}_id": person.get(f"{label}_id")}
        try:
            if person.get("erro_origem"):
                raise IntegrationError(person["erro_origem"])
            # Identidade é verificada antes do e-mail: contas já sincronizadas
            # continuam reconhecidas mesmo se o cadastro depois ficar incompleto.
            identity = map_identity(person, kind)["idnumber"]
            existing = destination.find("idnumber", identity)
            if len(existing) > 1:
                raise ValueError("Mais de uma conta possui a identidade do aluno.")
            if existing:
                item.update(status="existente", moodle_id=existing[0]["id"])
            else:
                user = map_user(person, kind)
                if destination.find("username", user["username"]):
                    raise ValueError("Login ocupado por uma conta sem o vínculo esperado.")
                if destination.find("email", user["email"]):
                    raise ValueError("E-mail já utilizado por outra conta no Moodle.")
                if dry_run:
                    item["status"] = "a_criar"
                else:
                    item.update(status="criado", moodle_id=destination.create(user))
        except (ValueError, IntegrationError) as exc:
            item.update(status="erro", mensagem=str(exc))
        results.append(item)
    return {"dry_run": dry_run, "total": len(results),
            "resumo": {status: sum(r["status"] == status for r in results)
                       for status in ("criado", "existente", "a_criar", "erro")},
            "alunos" if kind == "students" else "professores": results}
