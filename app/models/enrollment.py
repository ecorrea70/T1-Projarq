"""Modelos e regras de validação de vínculos docentes e enturmações de alunos."""
from collections import defaultdict

from app.core.errors import IntegrationError
from app.models.course import map_course


def validate_teacher_links(teachers: list[dict], courses: dict) -> None:
    """Valida se todos os vínculos docentes apontam para disciplinas válidas do catálogo."""
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


def resolve_student_courses(students: list[dict], catalog: list[dict]):
    """Valida e resolve as disciplinas das turmas ativas de cada aluno a partir do catálogo."""
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
    return courses, student_courses
