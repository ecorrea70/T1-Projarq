from typing import Protocol

from email_validator import EmailNotValidError, validate_email

from app.clients import IntegrationError


class StudentSource(Protocol):
    def students(self) -> list[dict]: ...
    def teachers(self) -> list[dict]: ...
    def teaching_catalog(self) -> list[dict]: ...


class UserDestination(Protocol):
    def find(self, field: str, value: str) -> list[dict]: ...
    def create(self, user: dict) -> int: ...
    def check_teaching_setup(self) -> None: ...
    def find_course(self, field: str, value: str) -> list[dict]: ...
    def create_course(self, course: dict) -> int: ...
    def course_teachers(self, course_id: int) -> set[int]: ...
    def enrol_teacher(self, user_id: int, course_id: int) -> None: ...
    def check_student_setup(self) -> None: ...
    def course_students(self, course_id: int) -> set[int]: ...
    def enrol_students(self, user_ids: list[int], course_id: int) -> None: ...


def map_student(student, kind="students"):
    label = "aluno" if kind == "students" else "professor"
    code = student.get(f"{label}_id")
    if isinstance(code, bool) or not isinstance(code, int) or code < 0:
        raise ValueError(f"Código do {label} inválido.")
    name = " ".join(str(student.get("nome") or "").split())
    parts = name.rsplit(" ", 1)
    if not name:
        raise ValueError("Cadastro sem nome.")
    if len(parts) == 1:
        parts.append("-")  # Campo obrigatório no Moodle; não inventa sobrenome.
    if any(len(part) > 100 for part in parts):
        raise ValueError("Nome e sobrenome devem ter até 100 caracteres cada.")
    try:
        email = validate_email(str(student.get("email") or "").strip(), check_deliverability=False).normalized
        if len(email) > 100:
            raise ValueError("E-mail excede o limite do Moodle.")
    except EmailNotValidError:
        raise ValueError("Cadastro sem e-mail válido.") from None
    return {"username": f"ieducar-{label}-{code}", "idnumber": f"ieducar:{label}:{code}",
            "firstname": parts[0], "lastname": parts[1], "email": email}


def synchronize(source: StudentSource, destination: UserDestination, dry_run: bool, kind="students"):
    if kind not in {"students", "teachers"}:
        raise ValueError("Tipo de sincronização inválido.")
    students = source.students() if kind == "students" else source.teachers()
    if kind == "teachers":
        from app.teaching import synchronize_teaching
        return synchronize_teaching(students, source.teaching_catalog(), destination, dry_run)
    from app.enrollment import synchronize_students
    return synchronize_students(students, source.teaching_catalog(), destination, dry_run)


def synchronize_users(students, destination, dry_run, kind="students"):
    label = "aluno" if kind == "students" else "professor"
    results = []
    for student in students:
        item = {f"{label}_id": student.get(f"{label}_id")}
        try:
            if student.get("erro_origem"):
                raise IntegrationError(student["erro_origem"])
            # Identidade é verificada antes do e-mail: contas já sincronizadas
            # continuam reconhecidas mesmo se o cadastro depois ficar incompleto.
            code = student.get(f"{label}_id")
            if isinstance(code, bool) or not isinstance(code, int) or code < 0:
                raise ValueError("Código do aluno inválido.")
            identity = f"ieducar:{label}:{code}"
            existing = destination.find("idnumber", identity)
            if len(existing) > 1:
                raise ValueError("Mais de uma conta possui a identidade do aluno.")
            if existing:
                item.update(status="existente", moodle_id=existing[0]["id"])
            else:
                user = map_student(student, kind)
                if destination.find("username", user["username"]):
                    raise ValueError("Login ocupado por uma conta sem o vínculo esperado.")
                if destination.find("email", user["email"]):
                    raise ValueError("E-mail já utilizado por outra conta no Moodle.")
                if dry_run:
                    item["status"] = "a_criar"
                else:
                    item.update(status="criado", moodle_id=destination.create(user))
        except (ValueError, IntegrationError) as exc:
            item.update(status="erro", mensagem=str(exc))
        results.append(item)
    return {"dry_run": dry_run, "total": len(results),
            "resumo": {status: sum(r["status"] == status for r in results)
                       for status in ("criado", "existente", "a_criar", "erro")},
            "alunos" if kind == "students" else "professores": results}
