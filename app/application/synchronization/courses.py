"""Mapeamento, validação do catálogo e sincronização de cursos."""
from app.core.errors import IntegrationError


def map_course(record):
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
    return {"idnumber": f"ieducar:curso:{institution}:{year}:{classroom}:{discipline}",
            "shortname": f"ieducar-{institution}-{year}-t{classroom}-d{discipline}", "fullname": fullname}


def prepare_courses(catalog):
    courses = {}
    for record in catalog:
        mapped = map_course(record)
        key = (record["turma_id"], record["disciplina_id"])
        if key in courses and courses[key][1] != mapped:
            raise IntegrationError("Curso duplicado com dados divergentes.")
        courses[key] = (record, mapped)
    return courses


def synchronize_courses(courses, destination, dry_run):
    """Sincroniza o catálogo preparado após as validações do orquestrador."""
    course_results = {}
    for key, (record, mapped) in sorted(courses.items()):
        item = {"turma_id": key[0], "disciplina_id": key[1], **mapped}
        try:
            existing = destination.find_course("idnumber", mapped["idnumber"])
            if len(existing) > 1:
                raise IntegrationError("Mais de um curso possui a mesma identidade.")
            if existing:
                item.update(status="existente", moodle_id=existing[0]["id"])
            else:
                if destination.find_course("shortname", mapped["shortname"]):
                    raise IntegrationError("Nome curto ocupado por curso sem a identidade esperada.")
                if dry_run:
                    item["status"] = "a_criar"
                else:
                    item.update(status="criado", moodle_id=destination.create_course(mapped))
        except IntegrationError as exc:
            item.update(status="erro", mensagem=str(exc))
        course_results[key] = item
    return course_results
