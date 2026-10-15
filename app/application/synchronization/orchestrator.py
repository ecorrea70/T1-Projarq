"""Orquestra a leitura da origem e a execução do fluxo escolhido."""
from app.application.contracts import StudentSource, UserDestination
from app.application.synchronization.courses import prepare_courses, synchronize_courses
from app.application.synchronization.students import synchronize_students
from app.application.reporting import report
from app.application.synchronization.teachers import synchronize_teaching, validate_teacher_links
from app.core.log import logger


def synchronize(source: StudentSource, destination: UserDestination, dry_run: bool, kind="students"):
    if kind not in {"students", "teachers"}:
        raise ValueError("Tipo de sincronização inválido.")
    log = logger()
    label = "alunos" if kind == "students" else "professores"
    log.info("Lendo %s no i-Educar.", label)
    students = source.students() if kind == "students" else source.teachers()
    log.info("i-Educar devolveu %d %s.", len(students), label)
    if kind == "teachers":
        # Valida catálogo, vínculos e configuração antes de qualquer escrita.
        log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
        courses = prepare_courses(source.teaching_catalog())
        log.info("Catálogo com %d cursos. Validando vínculos e a configuração do Moodle.", len(courses))
        validate_teacher_links(students, courses)
        destination.check_teaching_setup()
        log.info("Sincronizando %d cursos no Moodle.", len(courses))
        course_results = synchronize_courses(courses, destination, dry_run)
        log.info("Sincronizando contas e vínculos de %d professores.", len(students))
        result = synchronize_teaching(students, course_results, destination, dry_run)
        result["cursos"] = report(list(course_results.values()), ("criado", "existente", "a_criar", "erro"))
        return result
    log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
    catalog = source.teaching_catalog()
    log.info("Catálogo com %d cursos. Sincronizando %d alunos.", len(catalog), len(students))
    return synchronize_students(students, catalog, destination, dry_run)
