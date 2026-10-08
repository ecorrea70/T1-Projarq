"""Cursos por turma/disciplina e matrícula docente; toda comunicação é HTTP."""
from app.clients import IntegrationError
from app.sync import synchronize_users


def map_course(record):
    keys = ("instituicao_id", "ano", "turma_id", "disciplina_id")
    if any(type(record.get(key)) is not int or record[key] < 1 for key in keys):
        raise IntegrationError("Identificadores inválidos no catálogo de cursos.")
    names = [record.get(key) for key in ("turma_nome", "disciplina_nome")]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise IntegrationError("Nome de turma ou disciplina ausente no catálogo.")
    institution, year, classroom, discipline = (record[key] for key in keys)
    fullname = f"{names[1].strip()} — {names[0].strip()} (turma {classroom}) — {year}"
    if len(fullname) > 254:
        raise IntegrationError("Nome do curso excede o limite do Moodle.")
    return {"idnumber": f"ieducar:curso:{institution}:{year}:{classroom}:{discipline}",
            "shortname": f"ieducar-{institution}-{year}-t{classroom}-d{discipline}", "fullname": fullname}


def report(items, statuses):
    return {"total": len(items), "resumo": {s: sum(r["status"] == s for r in items) for s in statuses},
            "resultados": items}


def synchronize_teaching(teachers, catalog, destination, dry_run):
    # Valida toda a origem e configuração antes da primeira escrita externa.
    courses = {}
    for record in catalog:
        mapped = map_course(record)
        key = (record["turma_id"], record["disciplina_id"])
        if key in courses and courses[key][1] != mapped:
            raise IntegrationError("Curso duplicado com dados divergentes.")
        courses[key] = (record, mapped)
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
    destination.check_teaching_setup()
    course_results = {}
    for key, (record, mapped) in sorted(courses.items()):
        item = {"turma_id": key[0], "disciplina_id": key[1], **mapped}
        try:
            existing = destination.find_course("idnumber", mapped["idnumber"])
            if len(existing) > 1:
                raise IntegrationError("Mais de um curso possui a mesma identidade.")
            if existing:
                item.update(status="existente", moodle_id=existing[0]["id"])
            else:
                if destination.find_course("shortname", mapped["shortname"]):
                    raise IntegrationError("Nome curto ocupado por curso sem a identidade esperada.")
                if dry_run:
                    item["status"] = "a_criar"
                else:
                    item.update(status="criado", moodle_id=destination.create_course(mapped))
        except IntegrationError as exc:
            item.update(status="erro", mensagem=str(exc))
        course_results[key] = item

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
    result["cursos"] = report(list(course_results.values()), ("criado", "existente", "a_criar", "erro"))
    result["vinculos"] = report(memberships, ("vinculado", "existente", "a_vincular", "erro"))
    return result
