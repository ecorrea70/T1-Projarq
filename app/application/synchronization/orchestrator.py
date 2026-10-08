"""Orquestra a leitura da origem e a execução do fluxo escolhido."""
from app.application.contracts import StudentSource, UserDestination
from app.application.synchronization.courses import prepare_courses, synchronize_courses
from app.application.synchronization.students import synchronize_students
from app.application.reporting import report
from app.application.synchronization.teachers import synchronize_teaching, validate_teacher_links


def synchronize(source: StudentSource, destination: UserDestination, dry_run: bool, kind="students"):
    if kind not in {"students", "teachers"}:
        raise ValueError("Tipo de sincronização inválido.")
    students = source.students() if kind == "students" else source.teachers()
    if kind == "teachers":
        # Valida catálogo, vínculos e configuração antes de qualquer escrita.
        courses = prepare_courses(source.teaching_catalog())
        validate_teacher_links(students, courses)
        destination.check_teaching_setup()
        course_results = synchronize_courses(courses, destination, dry_run)
        result = synchronize_teaching(students, course_results, destination, dry_run)
        result["cursos"] = report(list(course_results.values()), ("criado", "existente", "a_criar", "erro"))
        return result
    return synchronize_students(students, source.teaching_catalog(), destination, dry_run)
