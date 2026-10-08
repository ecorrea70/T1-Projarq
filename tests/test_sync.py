import fcntl
import os
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.clients import IEducarClient, IntegrationError, MoodleClient
from app.config import ConfigurationError, Settings
from app.main import app
from app.sync import synchronize

SETTINGS = Settings("http://localhost", "rest-token", "http://localhost:8080",
                    "moodle-token", 15, "legacy-key", "1", "1", "2026", 1, 3, 5)


class Source:
    def __init__(self, rows):
        self.rows = rows

    def students(self):
        return self.rows

    def teachers(self):
        return self.rows

    def teaching_catalog(self):
        return [{"instituicao_id": 1, "escola_id": 1, "ano": 2026, "turma_id": 10, "turma_nome": "Turma A",
                 "disciplina_id": 2, "disciplina_nome": "Matemática"}]


class Moodle:
    def __init__(self):
        self.users = []
        self.courses = []
        self.enrolled = {}
        self.enrol_calls = 0
        self.student_enrolled = {}
        self.student_enrol_calls = 0

    def check_student_setup(self):
        pass

    def course_students(self, course_id):
        return set(self.student_enrolled.get(course_id, set()))

    def enrol_students(self, user_ids, course_id):
        self.student_enrol_calls += 1
        self.student_enrolled.setdefault(course_id, set()).update(user_ids)

    def check_teaching_setup(self):
        pass

    def find_course(self, field, value):
        return [c for c in self.courses if c.get(field) == value]

    def create_course(self, course):
        identifier = len(self.courses) + 20
        self.courses.append({**course, "id": identifier})
        return identifier

    def course_teachers(self, course_id):
        return set(self.enrolled.get(course_id, set()))

    def enrol_teacher(self, user_id, course_id):
        self.enrol_calls += 1
        self.enrolled.setdefault(course_id, set()).add(user_id)

    def find(self, field, value):
        return [u for u in self.users if u.get(field) == value]

    def create(self, user):
        identifier = len(self.users) + 10
        self.users.append({**user, "id": identifier})
        return identifier


def student(code=1, email="aluno@escola.edu.br"):
    return {"aluno_id": code, "nome": "Ana Maria da Silva", "email": email, "turmas": []}


class SyncTests(unittest.TestCase):
    def test_create_and_repeat(self):
        destination = Moodle()
        source = Source([student()])
        first = synchronize(source, destination, False)
        second = synchronize(source, destination, False)
        self.assertEqual(first["resumo"]["criado"], 1)
        self.assertEqual(second["resumo"]["existente"], 1)
        self.assertEqual(len(destination.users), 1)
        self.assertEqual(destination.users[0]["idnumber"], "ieducar:aluno:1")
        self.assertEqual(destination.users[0]["firstname"], "Ana Maria da")

    def test_dry_run_does_not_write(self):
        destination = Moodle()
        result = synchronize(Source([student()]), destination, True)
        self.assertEqual(result["resumo"]["a_criar"], 1)
        self.assertEqual(destination.users, [])

    def test_invalid_email_does_not_block_other_students(self):
        destination = Moodle()
        result = synchronize(Source([student(email=None), student(2)]), destination, False)
        self.assertEqual(result["resumo"]["erro"], 1)
        self.assertEqual(result["resumo"]["criado"], 1)

    def test_conflicts_are_not_adopted(self):
        for field, value in (("username", "ieducar-aluno-1"), ("email", "aluno@escola.edu.br")):
            with self.subTest(field=field):
                destination = Moodle()
                destination.users = [{"id": 8, field: value}]
                result = synchronize(Source([student()]), destination, False)
                self.assertEqual(result["resumo"]["erro"], 1)
                self.assertEqual(len(destination.users), 1)

    def test_create_failure_isolated(self):
        destination = Moodle()
        original = destination.create
        def create(user):
            if user["username"].endswith("-1"):
                raise IntegrationError("Falha de criação.")
            return original(user)
        destination.create = create
        result = synchronize(Source([student(), student(2, "outro@escola.edu.br")]), destination, False)
        self.assertEqual(result["resumo"]["erro"], 1)
        self.assertEqual(result["resumo"]["criado"], 1)

    def test_invalid_name_and_duplicate_identity(self):
        destination = Moodle()
        invalid = {**student(), "nome": ""}
        self.assertEqual(synchronize(Source([invalid]), destination, False)["resumo"]["erro"], 1)
        destination.users = [{"id": i, "idnumber": "ieducar:aluno:1"} for i in (1, 2)]
        self.assertEqual(synchronize(Source([student()]), destination, False)["resumo"]["erro"], 1)

    def test_single_word_name(self):
        destination = Moodle()
        result = synchronize(Source([{**student(), "nome": "Aluno001"}]), destination, False)
        self.assertEqual(result["resumo"]["criado"], 1)
        self.assertEqual(destination.users[0]["firstname"], "Aluno001")
        self.assertEqual(destination.users[0]["lastname"], "-")

    def test_existing_identity_survives_missing_email(self):
        destination = Moodle()
        synchronize(Source([student()]), destination, False)
        result = synchronize(Source([student(email=None)]), destination, False)
        self.assertEqual(result["resumo"]["existente"], 1)

    def test_origin_failure_creates_nothing(self):
        source = MagicMock()
        source.students.side_effect = IntegrationError("Origem indisponível.")
        destination = MagicMock()
        with self.assertRaises(IntegrationError):
            synchronize(source, destination, False)
        destination.create.assert_not_called()


class ClientTests(unittest.TestCase):
    @staticmethod
    def registration(code=1, active=1, student_active=1):
        return {"id": 100 + code, "student_id": code, "ativo": active,
                "ano": 2026, "ref_ref_cod_escola": 1, "enrollments": [],
                "student": {"id": code, "ativo": student_active,
                            "person": {"name": "Ana Silva", "email": "ana@escola.edu.br"}}}

    @staticmethod
    def page(rows, current=1, last=1):
        return {"data": rows, "meta": {"current_page": current, "last_page": last}}

    def test_paginated_enrollments_deduplicates_and_filters_inactive(self):
        client = IEducarClient(SETTINGS)
        pages = [self.page([self.registration(), self.registration(2, active=0)], 1, 2),
                 self.page([self.registration(), self.registration(3, student_active=0), self.registration(4)], 2, 2)]
        with patch.object(client, "get", side_effect=pages) as get:
            rows = client.students()
            self.assertEqual([row["aluno_id"] for row in rows], [1, 4])
            self.assertEqual(get.call_args.args[0], "/api/registration")
            self.assertEqual(get.call_args.args[1]["page"], 2)
            self.assertIn("student.person", get.call_args.args[1]["include"])
            self.assertIn("pmieducar.matricula.ativo", get.call_args.args[1]["only"])

    def test_multiple_schools_deduplicate_students(self):
        from dataclasses import replace
        client = IEducarClient(replace(SETTINGS, school_id="2,3"))
        rows2 = [{**self.registration(), "ref_ref_cod_escola": 2}]
        rows3 = [{**self.registration(), "ref_ref_cod_escola": 3}, {**self.registration(2), "ref_ref_cod_escola": 3}]
        with patch.object(client, "get", side_effect=[self.page(rows2), self.page(rows3)]) as get:
            rows = client.students()
            self.assertEqual([row["aluno_id"] for row in rows], [1, 2])
            self.assertEqual([call.args[1]["school"] for call in get.call_args_list], ["2", "3"])

    def test_later_page_failure_aborts_before_any_creation(self):
        client = IEducarClient(SETTINGS)
        destination = MagicMock()
        with patch.object(client, "get", side_effect=[self.page([self.registration()], 1, 2), IntegrationError("Falha.")]):
            with self.assertRaises(IntegrationError):
                synchronize(client, destination, False)
        destination.create.assert_not_called()

    def test_invalid_pagination_and_mismatched_student(self):
        client = IEducarClient(SETTINGS)
        mismatch = self.registration()
        mismatch["student_id"] = 2
        for response in (self.page([], 1, 0), self.page([mismatch])):
            with patch.object(client, "get", return_value=response), self.assertRaises(IntegrationError):
                client.students()

    def test_missing_email_is_not_invented(self):
        client = IEducarClient(SETTINGS)
        row = self.registration()
        del row["student"]["person"]["email"]
        with patch.object(client, "get", return_value=self.page([row])), patch.object(client, "teaching_catalog", return_value=[]):
            result = synchronize(client, Moodle(), False)
        self.assertEqual(result["resumo"]["erro"], 1)
        self.assertEqual(result["resumo"]["criado"], 0)

    def test_only_active_teaching_links_and_server_are_used(self):
        client = IEducarClient(SETTINGS)
        responses = [
            {"vinculos": [{"servidor_id": "7", "deleted_at": None, "turma_id": 10, "disciplinas": [{"id": 2}, {"id": 2}]},
                          {"servidor_id": "7", "deleted_at": None, "turma_id": 10, "disciplinas": [{"id": 2}]},
                          {"servidor_id": "8", "deleted_at": "2026-01-01"},
                          {"servidor_id": "9", "deleted_at": None, "turma_id": 10, "disciplinas": [{"id": 2}]}]},
            {"result": {"servidor_id": "7", "ativo": "1", "nome": "Maria Silva", "email": "maria@escola.edu.br"}},
            {"result": {"servidor_id": "9", "ativo": "0"}},
        ]
        with patch.object(client, "get", side_effect=responses) as get:
            rows = client.teachers()
            self.assertEqual([r["professor_id"] for r in rows], [7])
            self.assertEqual(rows[0]["vinculos"], [{"turma_id": 10, "disciplina_id": 2}])
            self.assertEqual(get.call_args_list[0].args[1]["resource"], "servidores-disciplinas-turmas")
            self.assertEqual(get.call_count, 3)

    def test_teacher_detail_error_does_not_create_account(self):
        client = IEducarClient(SETTINGS)
        with patch.object(client, "get", side_effect=[{"vinculos": [{"servidor_id": 7, "deleted_at": None, "turma_id": 10, "disciplinas": [{"id": 2}]}]}, IntegrationError("Falha da API."), {"turmas": []}]):
            result = synchronize(client, Moodle(), False, "teachers")
        self.assertEqual(result["resumo"]["erro"], 1)
        self.assertEqual(result["resumo"]["criado"], 0)

    def test_teacher_creation_and_repeat(self):
        source = Source([{"professor_id": 7, "nome": "Maria Silva", "email": "maria@escola.edu.br",
                          "vinculos": [{"turma_id": 10, "disciplina_id": 2}]}])
        destination = Moodle()
        first = synchronize(source, destination, False, "teachers")
        second = synchronize(source, destination, False, "teachers")
        self.assertEqual(first["resumo"]["criado"], 1)
        self.assertEqual(second["resumo"]["existente"], 1)
        self.assertEqual(destination.users[0]["idnumber"], "ieducar:professor:7")
        self.assertIn("professores", second)
        self.assertEqual(first["vinculos"]["resumo"]["vinculado"], 1)
        self.assertEqual(second["vinculos"]["resumo"]["existente"], 1)
        self.assertEqual(destination.enrol_calls, 1)

    def test_rest_request_uses_bearer_and_get(self):
        with patch("app.clients.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"data":[]}'
            IEducarClient(SETTINGS).get("/api/registration", {"page": 1})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer rest-token")
            self.assertNotIn("rest-token", request.full_url)

    def test_legacy_request_and_error_envelope(self):
        with patch("app.clients.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"any_error_msg":true,"msgs":["secret"]}'
            with self.assertRaises(IntegrationError) as exc:
                IEducarClient(SETTINGS).get("/module/Api/Servidor", {"resource": "dados-servidor"}, legacy=True)
            request = opener.return_value.open.call_args.args[0]
            self.assertIn("access_key=legacy-key", request.full_url)
            self.assertNotIn("secret", str(exc.exception))

    def test_moodle_payload_and_no_shared_password(self):
        client = MoodleClient(SETTINGS)
        with patch.object(client, "call", return_value=[{"id": 10}]) as call:
            client.create({"username": "ieducar-aluno-1"})
            first = call.call_args.args[1]
            client.create({"username": "ieducar-aluno-2"})
            second = call.call_args.args[1]
            self.assertNotEqual(first["users[0][password]"], second["users[0][password]"])
            self.assertNotIn("users[0][createpassword]", first)

    def test_http_200_moodle_exception_is_error(self):
        with patch("app.clients.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"exception":"moodle_exception","message":"secret"}'
            with self.assertRaises(IntegrationError) as exc:
                MoodleClient(SETTINGS).find("idnumber", "ieducar:aluno:1")
            self.assertNotIn("secret", str(exc.exception))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_and_missing_configuration(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.post("/sync/students", json={}).status_code, 503)

    def test_auth_and_default_simulation(self):
        with patch.dict(os.environ, {"SYNC_API_TOKEN": "test"}), patch("app.main.Settings.from_env", return_value=SETTINGS), patch("app.main.synchronize", return_value={}) as sync:
            self.assertEqual(self.client.post("/sync/students", json={}).status_code, 401)
            response = self.client.post("/sync/students", json={}, headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(sync.call_args.args[2])

    def test_concurrent_execution_rejected(self):
        with open("/tmp/t1-monolith-students.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.dict(os.environ, {"SYNC_API_TOKEN": "test"}), patch("app.main.Settings.from_env", return_value=SETTINGS):
                response = self.client.post("/sync/students", json={}, headers={"Authorization": "Bearer test"})
                self.assertEqual(response.status_code, 409)

    def test_teacher_route_selects_teacher_source(self):
        with patch.dict(os.environ, {"SYNC_API_TOKEN": "test"}), patch("app.main.Settings.from_env", return_value=SETTINGS) as settings, patch("app.main.synchronize", return_value={}) as sync:
            response = self.client.post("/sync/teachers", json={}, headers={"Authorization": "Bearer test"})
            self.assertEqual(response.status_code, 200)
            settings.assert_called_once_with("teachers")
            self.assertEqual(sync.call_args.args[3], "teachers")


class ConfigurationTests(unittest.TestCase):
    def test_database_credentials_cannot_replace_api_token(self):
        with patch.dict(os.environ, {"IEDUCAR_DB_PASSWORD": "secret", "IEDUCAR_URL": "http://localhost", "MOODLE_URL": "http://localhost:8080", "MOODLE_TOKEN": "test"}, clear=True):
            with self.assertRaises(ConfigurationError) as exc:
                Settings.from_env()
            self.assertIn("IEDUCAR_TOKEN", str(exc.exception))

    def test_teachers_require_legacy_key_and_scope(self):
        with patch.dict(os.environ, {"IEDUCAR_URL": "http://localhost", "IEDUCAR_TOKEN": "rest", "MOODLE_URL": "http://localhost:8080", "MOODLE_TOKEN": "test"}, clear=True):
            with self.assertRaises(ConfigurationError) as exc:
                Settings.from_env("teachers")
            self.assertIn("IEDUCAR_ACCESS_KEY", str(exc.exception))
            self.assertIn("IEDUCAR_SCHOOL_ID", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
