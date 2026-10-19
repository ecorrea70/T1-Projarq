"""Orquestra a leitura da origem e a execução do fluxo escolhido."""
from app.application.contracts import StudentSource, UserDestination
from app.application.synchronization.courses import prepare_courses, synchronize_courses
from app.application.synchronization.students import synchronize_students
from app.application.reporting import report
from app.application.synchronization.teachers import synchronize_teaching, validate_teacher_links
from app.core.log import logger
from app.core.progress import progress


def synchronize(source: StudentSource, destination: UserDestination, kind="students"):
    if kind not in {"students", "teachers"}:
        raise ValueError("Tipo de sincronização inválido.")
    log = logger()
    label = "alunos" if kind == "students" else "professores"
    progress.advance(f"Lendo {label} no i-Educar", 0, None, None)
    log.info("Lendo %s no i-Educar.", label)
    students = source.students() if kind == "students" else source.teachers()
    log.info("i-Educar devolveu %d %s.", len(students), label)
    progress.advance(f"Lendo {label} no i-Educar", len(students), len(students))
    if kind == "teachers":
        # Valida catálogo, vínculos e configuração antes de qualquer escrita.
        progress.advance("Lendo catálogo de turmas e disciplinas", 0, None, None)
        log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
        courses = prepare_courses(source.teaching_catalog())
        log.info("Catálogo com %d cursos. Validando vínculos e a configuração do Moodle.", len(courses))
        progress.advance("Validando vínculos e configuração do Moodle", 0, len(courses), None)
        validate_teacher_links(students, courses)
        destination.check_teaching_setup()
        log.info("Sincronizando %d cursos no Moodle.", len(courses))
        course_results = synchronize_courses(courses, destination)
        progress.advance("Sincronizando contas e vínculos", 0, len(students), None)
        log.info("Sincronizando contas e vínculos de %d professores.", len(students))
        result = synchronize_teaching(students, course_results, destination)
        result["cursos"] = report(list(course_results.values()), ("criado", "existente", "erro"))
        return result
    progress.advance("Lendo catálogo de turmas e disciplinas", 0, None, None)
    log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
    catalog = source.teaching_catalog()
    log.info("Catálogo com %d cursos. Sincronizando %d alunos.", len(catalog), len(students))
    progress.advance("Sincronizando alunos", 0, len(students), None)
    return synchronize_students(students, catalog, destination)
