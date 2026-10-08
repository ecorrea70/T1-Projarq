import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from app.infrastructure.clients.http import NoRedirect
from app.core.config import Settings
from app.core.errors import IntegrationError


class IEducarClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get(self, path, params, legacy=False):
        headers = {"Accept": "application/json"}
        if legacy:
            params = {**params, "access_key": self.settings.ieducar_access_key, "oper": "get"}
        else:
            headers["Authorization"] = "Bearer " + self.settings.ieducar_token
        request = Request(self.settings.ieducar_url + path + "?" + urlencode(params), headers=headers)
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.settings.timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise IntegrationError("Falha na API do i-Educar; confira disponibilidade, credencial e endpoint.") from None
        if not isinstance(result, dict) or result.get("any_error_msg") or "exception" in result:
            raise IntegrationError("A API do i-Educar recusou a consulta ou retornou dados inválidos.")
        return result

    @staticmethod
    def identifier(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdecimal():
            raise IntegrationError("Identificador inválido na API do i-Educar.")
        return int(value)

    @staticmethod
    def active(value):
        return value in (1, "1", True)

    def students(self):
        students = {}
        for school in self.settings.school_id.split(","):
            for record in self._students_for_school(school):
                self.merge_student(students, record)
        return list(students.values())

    @staticmethod
    def merge_student(students, record):
        code = record["aluno_id"]
        if code not in students:
            students[code] = record
            return
        previous = students[code]
        if any(previous[k] != record[k] for k in ("nome", "email")):
            raise IntegrationError("Dados divergentes para o mesmo aluno na API.")
        classes = {(r["turma_id"], r["ano"], r["escola_id"]) for r in previous["turmas"] + record["turmas"]}
        previous["turmas"] = [{"turma_id": t, "ano": y, "escola_id": s} for t, y, s in sorted(classes)]

    def _students_for_school(self, school):
        students = {}
        page = 1
        while True:
            params = {"include": "student:id,person_id,ativo|student.person:id,name,email|"
                                 "enrollments:id,ref_cod_matricula,ref_cod_turma,ativo,transferido,remanejado,abandono,falecido,reclassificado,data_exclusao",
                      "only": "id,student_id,pmieducar.matricula.ativo,ano,ref_ref_cod_escola", "order": "cod_matricula,asc",
                      "show": 100, "page": page}
            for key, value in (("institution", self.settings.institution_id),
                               ("school", school), ("yearEq", self.settings.year)):
                if value:
                    params[key] = value
            result = self.get("/api/registration", params)
            rows, meta = result.get("data"), result.get("meta")
            if not isinstance(rows, list) or not isinstance(meta, dict):
                raise IntegrationError("Resposta paginada de matrículas inválida.")
            last = meta.get("last_page")
            if type(last) is not int or last < page or meta.get("current_page") != page or last > 10000:
                raise IntegrationError("Paginação de matrículas inválida.")
            for row in rows:
                if not isinstance(row, dict):
                    raise IntegrationError("Matrícula inválida na API do i-Educar.")
                if "ativo" not in row:
                    raise IntegrationError("Situação da matrícula ausente na API.")
                if not self.active(row.get("ativo")):
                    continue
                student = row.get("student")
                if not isinstance(student, dict):
                    raise IntegrationError("A API não incluiu o aluno da matrícula.")
                if "ativo" not in student:
                    raise IntegrationError("Situação do aluno ausente na API.")
                if not self.active(student.get("ativo")):
                    continue
                code = self.identifier(student.get("id"))
                if self.identifier(row.get("student_id")) != code:
                    raise IntegrationError("Aluno divergente do vínculo da matrícula.")
                person = student.get("person")
                if not isinstance(person, dict):
                    person = {}
                registration_id = self.identifier(row.get("id"))
                year = self.identifier(row.get("ano"))
                school_id = self.identifier(row.get("ref_ref_cod_escola"))
                if (self.settings.year and year != int(self.settings.year)) or (school and school_id != int(school)):
                    raise IntegrationError("Matrícula fora do escopo solicitado.")
                enrollments = row.get("enrollments")
                if not isinstance(enrollments, list):
                    raise IntegrationError("Enturmações ausentes na API do i-Educar.")
                classes = set()
                flags = ("transferido", "remanejado", "abandono", "falecido", "reclassificado")
                for enrollment in enrollments:
                    if not isinstance(enrollment, dict) or "ativo" not in enrollment:
                        raise IntegrationError("Enturmação inválida na API do i-Educar.")
                    if self.identifier(enrollment.get("ref_cod_matricula")) != registration_id:
                        raise IntegrationError("Enturmação não corresponde à matrícula.")
                    if any(flag not in enrollment or enrollment[flag] not in (None, 0, 1, "0", "1", False, True) for flag in flags):
                        raise IntegrationError("Situação da enturmação ausente ou inválida.")
                    if not self.active(enrollment["ativo"]) or any(self.active(enrollment[f]) for f in flags) or enrollment.get("data_exclusao"):
                        continue
                    classes.add(self.identifier(enrollment.get("ref_cod_turma")))
                record = {"aluno_id": code, "nome": person.get("name"), "email": person.get("email"),
                          "turmas": [{"turma_id": t, "ano": year, "escola_id": school_id} for t in sorted(classes)]}
                self.merge_student(students, record)
            if page == last:
                break
            page += 1
        return list(students.values())

    def teachers(self):
        result = self.get("/module/Api/Servidor", {
            "resource": "servidores-disciplinas-turmas", "instituicao_id": self.settings.institution_id,
            "escola": self.settings.school_id, "ano": self.settings.year,
        }, legacy=True)
        links = result.get("vinculos")
        if not isinstance(links, list):
            raise IntegrationError("Resposta de vínculos de professores inválida.")
        codes = {}
        for link in links:
            if not isinstance(link, dict) or "deleted_at" not in link:
                raise IntegrationError("Vínculo de professor inválido.")
            if link["deleted_at"] is None:
                code = self.identifier(link.get("servidor_id"))
                classroom = self.identifier(link.get("turma_id"))
                disciplines = link.get("disciplinas")
                if not isinstance(disciplines, list) or not disciplines:
                    raise IntegrationError("Disciplinas ausentes no vínculo docente.")
                for discipline in disciplines:
                    if not isinstance(discipline, dict):
                        raise IntegrationError("Disciplina inválida no vínculo docente.")
                    codes.setdefault(code, set()).add((classroom, self.identifier(discipline.get("id"))))
        teachers = []
        for code in sorted(codes):
            try:
                response = self.get("/module/Api/Servidor", {"resource": "dados-servidor", "servidor_id": code}, legacy=True)
                record = response.get("result")
                if not isinstance(record, dict) or self.identifier(record.get("servidor_id")) != code:
                    raise IntegrationError("Dados do professor não correspondem ao vínculo.")
                if "ativo" not in record:
                    raise IntegrationError("Situação do professor ausente na API.")
                if self.active(record["ativo"]):
                    teachers.append({"professor_id": code, "nome": record.get("nome"), "email": record.get("email"),
                                     "vinculos": [{"turma_id": t, "disciplina_id": d} for t, d in sorted(codes[code])]})
            except IntegrationError as exc:
                teachers.append({"professor_id": code, "erro_origem": str(exc)})
        return teachers

    def teaching_catalog(self):
        result = self.get("/module/Api/Turma", {
            "resource": "turmas-por-escola", "instituicao_id": self.settings.institution_id,
            "escola": self.settings.school_id, "ano": self.settings.year,
        }, legacy=True)
        classes = result.get("turmas")
        if not isinstance(classes, list):
            raise IntegrationError("Catálogo de turmas inválido.")
        courses = {}
        for classroom in classes:
            if not isinstance(classroom, dict) or "deleted_at" not in classroom:
                raise IntegrationError("Turma inválida no catálogo.")
            if classroom["deleted_at"] is not None:
                continue
            code = self.identifier(classroom.get("id"))
            year = self.identifier(classroom.get("ano"))
            school = self.identifier(classroom.get("escola_id"))
            if year != int(self.settings.year) or str(school) not in self.settings.school_id.split(","):
                raise IntegrationError("Turma fora do escopo solicitado.")
            result = self.get("/module/Api/ComponenteCurricular", {
                "resource": "componentes-curriculares-for-multiple-search",
                "instituicao_id": self.settings.institution_id, "turma_id": code,
                "ano": year, "allDisciplinesMulti": "true",
            }, legacy=True)
            options = result.get("options")
            # PHP serializa um mapa vazio como [] e mapas de IDs como objetos.
            if options == []:
                options = {}
            if not isinstance(options, dict):
                raise IntegrationError("Catálogo de disciplinas inválido.")
            for discipline, name in options.items():
                discipline = self.identifier(discipline)
                record = {"instituicao_id": int(self.settings.institution_id), "ano": year,
                          "escola_id": school, "turma_id": code, "turma_nome": classroom.get("nome"),
                          "disciplina_id": discipline, "disciplina_nome": name}
                key = (code, discipline)
                if key in courses and courses[key] != record:
                    raise IntegrationError("Curso divergente no catálogo da API.")
                courses[key] = record
        return list(courses.values())
