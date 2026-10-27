"""Mapeamento, validação do catálogo e sincronização de cursos."""
from app.application.contracts import CourseRepository
from app.core.errors import IntegrationError
from app.core.log import logger
from app.core.progress import progress
from app.models.course import CourseModel, build_course_model, map_course, prepare_courses


def synchronize_courses(courses: dict, destination: CourseRepository) -> dict:
    """Sincroniza o catálogo preparado após as validações do orquestrador."""
    course_results = {}
    ordered = sorted(courses.items())
    log = logger()
    total = len(ordered)
    for index, (key, (record, mapped)) in enumerate(ordered, start=1):
        progress.advance("Sincronizando cursos", index - 1, total, f"turma {key[0]} disciplina {key[1]}")
        log.info("Curso %d/%d turma=%s disciplina=%s.", index, total, key[0], key[1])
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
                item.update(status="criado", moodle_id=destination.create_course(mapped))
        except IntegrationError as exc:
            item.update(status="erro", mensagem=str(exc))
        log.info("Curso %d/%d turma=%s disciplina=%s: %s.", index, total, key[0], key[1], item["status"])
        progress.advance("Sincronizando cursos", index, total, f"turma {key[0]} disciplina {key[1]}: {item['status']}")
        course_results[key] = item
    return course_results


__all__ = ["CourseModel", "build_course_model", "map_course", "prepare_courses", "synchronize_courses"]
