"""Modelos de curso e validação de catálogo entre i-Educar e Moodle."""
from dataclasses import dataclass

from app.core.errors import IntegrationError


@dataclass(frozen=True)
class CourseModel:
    """Representa um curso validado (turma + disciplina) para o Moodle."""
    idnumber: str
    shortname: str
    fullname: str

    def to_dict(self) -> dict[str, str]:
        return {
            "idnumber": self.idnumber,
            "shortname": self.shortname,
            "fullname": self.fullname,
        }


def build_course_model(record: dict) -> CourseModel:
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
    return CourseModel(
        idnumber=f"ieducar:curso:{institution}:{year}:{classroom}:{discipline}",
        shortname=f"ieducar-{institution}-{year}-t{classroom}-d{discipline}",
        fullname=fullname,
    )


def map_course(record: dict) -> dict[str, str]:
    return build_course_model(record).to_dict()


def prepare_courses(catalog: list[dict]) -> dict[tuple[int, int], tuple[dict, dict[str, str]]]:
    courses = {}
    for record in catalog:
        mapped = map_course(record)
        key = (record["turma_id"], record["disciplina_id"])
        if key in courses and courses[key][1] != mapped:
            raise IntegrationError("Curso duplicado com dados divergentes.")
        courses[key] = (record, mapped)
    return courses
