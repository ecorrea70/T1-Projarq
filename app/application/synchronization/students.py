"""Matrícula de alunos nos cursos existentes de suas turmas, pelas APIs."""
from collections import defaultdict

from app.application.accounts.synchronization import synchronize_users
from app.application.contracts import StudentEnrolmentDestination
from app.application.reporting import report
from app.core.errors import IntegrationError
from app.core.log import logger
from app.core.progress import progress
from app.models.enrollment import resolve_student_courses


def synchronize_students(students: list[dict], catalog: list[dict], destination: StudentEnrolmentDestination) -> dict:
    # Confere todos os vínculos da origem no Model antes de qualquer escrita.
    courses, student_courses = resolve_student_courses(students, catalog)
    destination.check_student_setup()
    course_results = {}
    needed = {key for keys in student_courses.values() for key in keys}
    ordered = sorted(needed)
    log = logger()
    log.info("Conferindo %d cursos já existentes no Moodle.", len(ordered))
    for index, key in enumerate(ordered, start=1):
        progress.advance("Conferindo cursos", index - 1, len(ordered), f"turma {key[0]} disciplina {key[1]}")
        log.info("Consulta de curso %d/%d turma=%s disciplina=%s.", index, len(ordered), key[0], key[1])
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
    result = synchronize_users(students, destination)
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
            else:
                item.update(moodle_user_id=account["moodle_id"], moodle_course_id=course["moodle_id"])
                per_course[course["moodle_id"]].append(item)
            memberships.append(item)
    course_total = len(per_course)
    for course_index, (course_id, items) in enumerate(per_course.items(), start=1):
        pending = []
        progress.advance("Matriculando alunos", course_index - 1, course_total, f"curso {course_id}")
        log.info("Matrículas do curso Moodle %s: %d alunos.", course_id, len(items))
        try:
            existing = destination.course_students(course_id)
            for item in items:
                if item["moodle_user_id"] in existing:
                    item["status"] = "existente"
                else:
                    pending.append(item)
            # Lotes por curso evitam uma requisição externa por aluno.
            for start in range(0, len(pending), 100):
                batch = pending[start:start + 100]
                progress.advance("Matriculando alunos", start, len(pending), f"curso {course_id}")
                log.info("Enviando matrículas %d-%d de %d no curso Moodle %s.", start + 1, start + len(batch), len(pending), course_id)
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
        else:
            account["matricula"] = "confirmada"
    result["cursos"] = report(list(course_results.values()), ("existente", "erro"))
    result["vinculos"] = report(memberships, ("vinculado", "existente", "erro"))
    return result
