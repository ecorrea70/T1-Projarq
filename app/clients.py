import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from app.config import Settings


class IntegrationError(Exception):
    """Erro sanitizado, sem incluir URLs, credenciais ou respostas externas."""


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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MoodleClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def call(self, function, params):
        data = urlencode({"wstoken": self.settings.moodle_token,
                          "moodlewsrestformat": "json", "wsfunction": function,
                          **params}).encode()
        request = Request(self.settings.moodle_url + "/webservice/rest/server.php", data=data)
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.settings.timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise IntegrationError("Falha de comunicação com o Moodle; reexecute para conferir o resultado.") from None
        if isinstance(result, dict) and ("exception" in result or "errorcode" in result):
            if result.get("errorcode") == "Message was not sent.":
                raise IntegrationError("O Moodle falhou ao enviar uma notificação; confira a configuração de e-mail/SMTP.")
            raise IntegrationError(f"O Moodle recusou {function}; confira função no serviço, token, permissões e dados.")
        return result

    def find(self, field, value):
        users = self.call("core_user_get_users_by_field", {"field": field, "values[0]": value})
        if not isinstance(users, list) or any(not isinstance(user, dict) or type(user.get("id")) is not int for user in users):
            raise IntegrationError("Resposta de consulta inválida do Moodle.")
        return users

    def create(self, user):
        # Senha aleatória individual, sem envio de mensagens nem exposição
        # na resposta. O primeiro acesso usa a recuperação de senha do Moodle.
        params = {f"users[0][{key}]": value for key, value in user.items()}
        result = self.call("core_user_create_users", {
            **params, "users[0][password]": secrets.token_urlsafe(32) + "aA1!",
            "users[0][auth]": "manual",
            "users[0][preferences][0][type]": "auth_forcepasswordchange",
            "users[0][preferences][0][value]": "1",
        })
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict) or type(result[0].get("id")) is not int:
            raise IntegrationError("Resposta de criação inválida; reexecute para conferir o resultado.")
        return result[0]["id"]

    def check_teaching_setup(self):
        self.check_functions({"core_user_get_users_by_field", "core_user_create_users", "core_course_get_categories",
                              "core_course_get_courses_by_field", "core_course_create_courses",
                              "core_enrol_get_enrolled_users", "enrol_manual_enrol_users"})
        categories = self.call("core_course_get_categories", {
            "criteria[0][key]": "id", "criteria[0][value]": self.settings.moodle_category_id})
        if not isinstance(categories, list) or len(categories) != 1 or not isinstance(categories[0], dict) or categories[0].get("id") != self.settings.moodle_category_id:
            raise IntegrationError("Categoria Moodle não encontrada ou não acessível.")

    def check_student_setup(self):
        self.check_functions({"core_user_get_users_by_field", "core_user_create_users",
                              "core_course_get_courses_by_field", "core_enrol_get_enrolled_users", "enrol_manual_enrol_users"})

    def check_functions(self, required):
        info = self.call("core_webservice_get_site_info", {})
        if not isinstance(info, dict) or not isinstance(info.get("functions"), list):
            raise IntegrationError("Resposta de funções disponíveis do Moodle inválida.")
        available = {f.get("name") for f in info["functions"] if isinstance(f, dict)}
        missing = required - available
        if missing:
            raise IntegrationError("Adicione ao serviço Moodle: " + ", ".join(sorted(missing)))

    def find_course(self, field, value):
        result = self.call("core_course_get_courses_by_field", {"field": field, "value": value})
        if not isinstance(result, dict) or not isinstance(result.get("courses"), list) or result.get("warnings"):
            raise IntegrationError("Consulta de cursos inválida ou com avisos no Moodle.")
        courses = result["courses"]
        if any(not isinstance(c, dict) or type(c.get("id")) is not int or c["id"] <= 1
               or str(c.get(field)) != str(value) for c in courses):
            raise IntegrationError("Identidade de curso inválida no Moodle.")
        return courses

    def create_course(self, course):
        result = self.call("core_course_create_courses", {
            **{f"courses[0][{key}]": value for key, value in course.items()},
            "courses[0][categoryid]": self.settings.moodle_category_id,
        })
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict) or type(result[0].get("id")) is not int or result[0]["id"] <= 1:
            raise IntegrationError("Resposta de criação de curso inválida; reexecute para conferir.")
        return result[0]["id"]

    def course_teachers(self, course_id):
        return self.course_users_with_role(course_id, self.settings.moodle_teacher_role_id)

    def course_students(self, course_id):
        return self.course_users_with_role(course_id, self.settings.moodle_student_role_id)

    def course_users_with_role(self, course_id, role_id):
        users = self.call("core_enrol_get_enrolled_users", {
            "courseid": course_id, "options[0][name]": "onlyactive", "options[0][value]": 1})
        if not isinstance(users, list):
            raise IntegrationError("Resposta de participantes inválida.")
        teachers = set()
        for user in users:
            if not isinstance(user, dict) or type(user.get("id")) is not int or not isinstance(user.get("roles"), list):
                raise IntegrationError("Papéis dos participantes ausentes na API Moodle.")
            if any(isinstance(role, dict) and role.get("roleid") == role_id for role in user["roles"]):
                teachers.add(user["id"])
        return teachers

    def enrol_teacher(self, user_id, course_id):
        self.enrol_users([user_id], course_id, self.settings.moodle_teacher_role_id)

    def enrol_students(self, user_ids, course_id):
        self.enrol_users(user_ids, course_id, self.settings.moodle_student_role_id)

    def enrol_users(self, user_ids, course_id, role_id):
        if not user_ids:
            return
        params = {}
        for index, user_id in enumerate(user_ids):
            params.update({f"enrolments[{index}][roleid]": role_id,
                           f"enrolments[{index}][userid]": user_id, f"enrolments[{index}][courseid]": course_id})
        result = self.call("enrol_manual_enrol_users", params)
        if result is not None:
            raise IntegrationError("Resposta inesperada de matrícula no Moodle; reexecute para conferir.")
