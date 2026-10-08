"""Matrícula de alunos nos cursos existentes de suas turmas, pelas APIs."""
from collections import defaultdict

from app.core.errors import IntegrationError
from app.application.accounts.synchronization import synchronize_users
from app.application.synchronization.courses import map_course
from app.application.reporting import report


def synchronize_students(students, catalog, destination, dry_run):
    courses = {}
    classrooms = defaultdict(set)
    for record in catalog:
        mapped = map_course(record)
        if type(record.get("escola_id")) is not int or record["escola_id"] < 1:
            raise IntegrationError("Escola do curso ausente ou inválida no catálogo.")
        key = (record["turma_id"], record["disciplina_id"])
        if key in courses and courses[key] != (record, mapped):
            raise IntegrationError("Curso duplicado com dados divergentes.")
        courses[key] = (record, mapped)
        classrooms[(record["turma_id"], record["ano"], record["escola_id"])].add(key)
    # Confere todos os vínculos da origem antes de qualquer escrita.
    student_courses = {}
    for student in students:
        classes = student.get("turmas")
        if not isinstance(classes, list):
            raise IntegrationError("Turmas do aluno ausentes na API.")
        keys = set()
        for classroom in classes:
            if not isinstance(classroom, dict) or any(type(classroom.get(k)) is not int for k in ("turma_id", "ano", "escola_id")):
                raise IntegrationError("Turma do aluno inválida.")
            scope = (classroom["turma_id"], classroom["ano"], classroom["escola_id"])
            if scope not in classrooms:
                raise IntegrationError("Turma ativa do aluno sem disciplinas no catálogo do escopo.")
            keys.update(classrooms[scope])
        student_courses[student["aluno_id"]] = keys
    destination.check_student_setup()
    course_results = {}
    needed = {key for keys in student_courses.values() for key in keys}
    for key in sorted(needed):
        mapped = courses[key][1]
        item = {"turma_id": key[0], "disciplina_id": key[1], "idnumber": mapped["idnumber"]}
        try:
            found = destination.find_course("idnumber", mapped["idnumber"])
            if len(found) != 1:
                raise IntegrationError("Curso ausente ou identidade duplicada no Moodle; sincronize os cursos dos professores.")
            item.update(status="existente", moodle_id=found[0]["id"])
        except IntegrationError as exc:
            item.update(status="erro", mensagem=str(exc))
        course_results[key] = item
    result = synchronize_users(students, destination, dry_run)
    accounts = {s["aluno_id"]: s for s in result["alunos"]}
    memberships = []
    per_course = defaultdict(list)
    for student in students:
        account = accounts[student["aluno_id"]]
        for key in sorted(student_courses[student["aluno_id"]]):
            course = course_results[key]
            item = {"aluno_id": student["aluno_id"], "turma_id": key[0], "disciplina_id": key[1]}
            if account["status"] == "erro" or course["status"] == "erro":
                item.update(status="erro", mensagem="Vínculo não realizado: consulta/criação do aluno ou consulta do curso falhou.")
            elif account.get("moodle_id") is None and dry_run:
                item["status"] = "a_vincular"
            else:
                item.update(moodle_user_id=account["moodle_id"], moodle_course_id=course["moodle_id"])
                per_course[course["moodle_id"]].append(item)
            memberships.append(item)
    for course_id, items in per_course.items():
        pending = []
        try:
            existing = destination.course_students(course_id)
            for item in items:
                if item["moodle_user_id"] in existing:
                    item["status"] = "existente"
                else:
                    pending.append(item)
            if dry_run:
                for item in pending:
                    item["status"] = "a_vincular"
            else:
                # Lotes por curso evitam uma requisição externa por aluno.
                for start in range(0, len(pending), 100):
                    batch = pending[start:start + 100]
                    try:
                        destination.enrol_students([i["moodle_user_id"] for i in batch], course_id)
                        confirmed = destination.course_students(course_id)
                        for item in batch:
                            if item["moodle_user_id"] in confirmed:
                                item["status"] = "vinculado"
                            else:
                                item.update(status="erro", mensagem="Matrícula enviada, mas papel Estudante não confirmado; reexecute para conferir.")
                    except IntegrationError as exc:
                        # Notificações podem falhar depois do commit da matrícula.
                        # Confere o estado real antes de declarar o vínculo como erro.
                        try:
                            confirmed = destination.course_students(course_id)
                        except IntegrationError:
                            confirmed = set()
                        for item in batch:
                            if item["moodle_user_id"] in confirmed:
                                item.update(status="vinculado", aviso=str(exc))
                            else:
                                item.update(status="erro", mensagem=str(exc))
        except IntegrationError as exc:
            for item in items:
                if "status" not in item:
                    item.update(status="erro", mensagem=str(exc))
    for account in result["alunos"]:
        own = [m for m in memberships if m["aluno_id"] == account["aluno_id"]]
        if account["status"] == "erro" or any(m["status"] == "erro" for m in own):
            account["matricula"] = "erro"
        elif not own:
            account["matricula"] = "sem_turma"
        elif any(m["status"] == "a_vincular" for m in own):
            account["matricula"] = "a_vincular"
        else:
            account["matricula"] = "confirmada"
    result["cursos"] = report(list(course_results.values()), ("existente", "erro"))
    result["vinculos"] = report(memberships, ("vinculado", "existente", "a_vincular", "erro"))
    return result
