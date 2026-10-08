"""Validação dos vínculos e sincronização de professores nos cursos."""
from app.core.errors import IntegrationError
from app.application.reporting import report
from app.application.accounts.synchronization import synchronize_users


def validate_teacher_links(teachers, courses):
    for teacher in teachers:
        if teacher.get("erro_origem"):
            continue
        links = teacher.get("vinculos")
        if not isinstance(links, list) or not links:
            raise IntegrationError("Professor sem vínculos docentes válidos na API.")
        for link in links:
            if not isinstance(link, dict) or any(type(link.get(k)) is not int for k in ("turma_id", "disciplina_id")):
                raise IntegrationError("Vínculo docente inválido.")
            if (link["turma_id"], link["disciplina_id"]) not in courses:
                raise IntegrationError("Disciplina do professor não consta no catálogo da turma; nenhuma escrita realizada.")


def synchronize_teaching(teachers, course_results, destination, dry_run):
    result = synchronize_users(teachers, destination, dry_run, "teachers")
    accounts = {u["professor_id"]: u for u in result["professores"]}
    memberships = []
    participants = {}
    for teacher in teachers:
        account = accounts[teacher["professor_id"]]
        seen = set()
        for link in teacher.get("vinculos", []):
            key = (link["turma_id"], link["disciplina_id"])
            if key in seen:
                continue
            seen.add(key)
            course = course_results[key]
            item = {"professor_id": teacher["professor_id"], "turma_id": key[0], "disciplina_id": key[1]}
            try:
                if account["status"] == "erro" or course["status"] == "erro":
                    raise IntegrationError("Vínculo não realizado: criação/consulta do usuário ou curso falhou.")
                user_id, course_id = account.get("moodle_id"), course.get("moodle_id")
                if user_id is not None and course_id is not None:
                    item.update(moodle_user_id=user_id, moodle_course_id=course_id)
                    if course_id not in participants:
                        participants[course_id] = destination.course_teachers(course_id)
                    if user_id in participants[course_id]:
                        item["status"] = "existente"
                    elif dry_run:
                        item["status"] = "a_vincular"
                    else:
                        destination.enrol_teacher(user_id, course_id)
                        # Confere o papel efetivo pela API após a matrícula.
                        participants[course_id] = destination.course_teachers(course_id)
                        if user_id not in participants[course_id]:
                            raise IntegrationError("Matrícula enviada, mas papel docente não confirmado; reexecute para conferir.")
                        item["status"] = "vinculado"
                elif dry_run:
                    item["status"] = "a_vincular"
                else:
                    raise IntegrationError("IDs do usuário/curso ausentes para matrícula.")
            except IntegrationError as exc:
                item.update(status="erro", mensagem=str(exc))
            memberships.append(item)
        own = [m for m in memberships if m["professor_id"] == teacher["professor_id"]]
        account["docencia"] = "erro" if account["status"] == "erro" or any(m["status"] == "erro" for m in own) else ("a_vincular" if dry_run and any(m["status"] == "a_vincular" for m in own) else "confirmada")
    result["vinculos"] = report(memberships, ("vinculado", "existente", "a_vincular", "erro"))
    return result
