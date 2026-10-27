"""Orquestra a leitura da origem e a execução da estratégia do fluxo escolhido (OCP / Strategy)."""
from typing import Protocol

from app.application.contracts import StudentSource, UserDestination
from app.application.reporting import report
from app.application.synchronization.courses import prepare_courses, synchronize_courses
from app.application.synchronization.students import synchronize_students
from app.application.synchronization.teachers import synchronize_teaching, validate_teacher_links
from app.core.log import logger
from app.core.progress import progress


class SyncStrategy(Protocol):
    """Contrato de estratégia de sincronização (Open/Closed e Liskov Substitution)."""
    kind: str
    label: str

    def execute(self, source: StudentSource, destination: UserDestination) -> dict: ...


class StudentSyncStrategy:
    """Estratégia de sincronização de alunos e matrículas."""
    kind = "students"
    label = "alunos"

    def execute(self, source: StudentSource, destination: UserDestination) -> dict:
        log = logger()
        progress.advance(f"Lendo {self.label} no i-Educar", 0, None, None)
        log.info("Lendo %s no i-Educar.", self.label)
        students = source.students()
        log.info("i-Educar devolveu %d %s.", len(students), self.label)
        progress.advance(f"Lendo {self.label} no i-Educar", len(students), len(students))
        progress.advance("Lendo catálogo de turmas e disciplinas", 0, None, None)
        log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
        catalog = source.teaching_catalog()
        log.info("Catálogo com %d cursos. Sincronizando %d alunos.", len(catalog), len(students))
        progress.advance("Sincronizando alunos", 0, len(students), None)
        return synchronize_students(students, catalog, destination)


class TeacherSyncStrategy:
    """Estratégia de sincronização de professores, cursos e vínculos docentes."""
    kind = "teachers"
    label = "professores"

    def execute(self, source: StudentSource, destination: UserDestination) -> dict:
        log = logger()
        progress.advance(f"Lendo {self.label} no i-Educar", 0, None, None)
        log.info("Lendo %s no i-Educar.", self.label)
        teachers = source.teachers()
        log.info("i-Educar devolveu %d %s.", len(teachers), self.label)
        progress.advance(f"Lendo {self.label} no i-Educar", len(teachers), len(teachers))
        # Valida catálogo, vínculos e configuração antes de qualquer escrita.
        progress.advance("Lendo catálogo de turmas e disciplinas", 0, None, None)
        log.info("Lendo catálogo de turmas e disciplinas no i-Educar.")
        courses = prepare_courses(source.teaching_catalog())
        log.info("Catálogo com %d cursos. Validando vínculos e a configuração do Moodle.", len(courses))
        progress.advance("Validando vínculos e configuração do Moodle", 0, len(courses), None)
        validate_teacher_links(teachers, courses)
        destination.check_teaching_setup()
        log.info("Sincronizando %d cursos no Moodle.", len(courses))
        course_results = synchronize_courses(courses, destination)
        progress.advance("Sincronizando contas e vínculos", 0, len(teachers), None)
        log.info("Sincronizando contas e vínculos de %d professores.", len(teachers))
        result = synchronize_teaching(teachers, course_results, destination)
        result["cursos"] = report(list(course_results.values()), ("criado", "existente", "erro"))
        return result


STRATEGIES: dict[str, SyncStrategy] = {
    "students": StudentSyncStrategy(),
    "teachers": TeacherSyncStrategy(),
}


def synchronize(source: StudentSource, destination: UserDestination, kind: str = "students") -> dict:
    strategy = STRATEGIES.get(kind)
    if strategy is None:
        raise ValueError("Tipo de sincronização inválido.")
    return strategy.execute(source, destination)
