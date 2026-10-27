"""Contratos das plataformas usados pela sincronização (ISP e DIP)."""
from typing import Protocol


class StudentCatalogReader(Protocol):
    """Contrato de leitura de alunos e catálogo de disciplinas (ISP)."""
    def students(self) -> list[dict]: ...
    def teaching_catalog(self) -> list[dict]: ...


class TeacherCatalogReader(Protocol):
    """Contrato de leitura de professores e catálogo de disciplinas (ISP)."""
    def teachers(self) -> list[dict]: ...
    def teaching_catalog(self) -> list[dict]: ...


class StudentSource(StudentCatalogReader, TeacherCatalogReader, Protocol):
    """Contrato unificado da fonte de dados acadêmicos (i-Educar)."""
    pass


class AccountRepository(Protocol):
    """Contrato de consulta e criação de contas de usuários no destino (ISP)."""
    def find(self, field: str, value: str) -> list[dict]: ...
    def create(self, user: dict) -> int: ...


class CourseRepository(Protocol):
    """Contrato de consulta e criação de cursos no destino (ISP)."""
    def find_course(self, field: str, value: str) -> list[dict]: ...
    def create_course(self, course: dict) -> int: ...


class TeacherEnrolmentDestination(AccountRepository, CourseRepository, Protocol):
    """Contrato de destino para sincronização docente (ISP)."""
    def check_teaching_setup(self) -> None: ...
    def course_teachers(self, course_id: int) -> set[int]: ...
    def enrol_teacher(self, user_id: int, course_id: int) -> None: ...


class StudentEnrolmentDestination(AccountRepository, Protocol):
    """Contrato de destino para sincronização de matrículas discentes (ISP)."""
    def check_student_setup(self) -> None: ...
    def find_course(self, field: str, value: str) -> list[dict]: ...
    def course_students(self, course_id: int) -> set[int]: ...
    def enrol_students(self, user_ids: list[int], course_id: int) -> None: ...


class UserDestination(TeacherEnrolmentDestination, StudentEnrolmentDestination, Protocol):
    """Contrato unificado da plataforma de destino (Moodle)."""
    pass
