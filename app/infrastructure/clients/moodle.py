import secrets
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from app.infrastructure.clients.http import NoRedirect
from app.core.config import Settings
from app.core.errors import IntegrationError


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
