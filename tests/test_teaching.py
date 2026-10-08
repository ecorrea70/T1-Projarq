import unittest
from dataclasses import replace
from unittest.mock import patch

from app.infrastructure.clients.ieducar import IEducarClient
from app.infrastructure.clients.moodle import MoodleClient
from app.core.errors import IntegrationError
from app.application.synchronization.orchestrator import synchronize
from test_sync import Moodle, SETTINGS, Source


def teacher(code=7):
    return {"professor_id": code, "nome": "Maria Silva", "email": f"maria{code}@escola.edu.br",
            "vinculos": [{"turma_id": 10, "disciplina_id": 2}]}


class TeachingTests(unittest.TestCase):
    def test_dry_run_has_no_mutations(self):
        destination = Moodle()
        result = synchronize(Source([teacher()]), destination, True, "teachers")
        self.assertEqual(result["cursos"]["resumo"]["a_criar"], 1)
        self.assertEqual(result["vinculos"]["resumo"]["a_vincular"], 1)
        self.assertEqual((destination.users, destination.courses, destination.enrolled), ([], [], {}))

    def test_existing_account_receives_role_and_multiple_teachers_share_course(self):
        destination = Moodle()
        destination.users = [{"id": 4, "idnumber": "ieducar:professor:7"}]
        result = synchronize(Source([teacher(), teacher(8)]), destination, False, "teachers")
        self.assertEqual(result["resumo"]["existente"], 1)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 2)
        self.assertEqual(len(destination.courses), 1)
        self.assertEqual(destination.enrolled[20], {4, 11})

    def test_distinct_classes_and_years_have_distinct_courses(self):
        from app.application.synchronization.courses import map_course
        record = Source([]).teaching_catalog()[0]
        ids = {map_course({**record, **changes})["idnumber"] for changes in ({}, {"turma_id": 11}, {"ano": 2027})}
        self.assertEqual(len(ids), 3)

    def test_unlinked_disciplines_also_become_courses(self):
        source = Source([teacher()])
        catalog = source.teaching_catalog()
        source.teaching_catalog = lambda: catalog + [{**catalog[0], "disciplina_id": 3, "disciplina_nome": "História"}]
        destination = Moodle()
        result = synchronize(source, destination, False, "teachers")
        self.assertEqual(result["cursos"]["resumo"]["criado"], 2)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 1)

    def test_missing_curriculum_aborts_before_writes(self):
        source = Source([teacher()])
        source.teaching_catalog = lambda: []
        destination = Moodle()
        with self.assertRaises(IntegrationError):
            synchronize(source, destination, False, "teachers")
        self.assertEqual(destination.users, [])

    def test_missing_service_aborts_before_writes(self):
        destination = Moodle()
        destination.check_teaching_setup = lambda: (_ for _ in ()).throw(IntegrationError("Função não habilitada"))
        with self.assertRaises(IntegrationError):
            synchronize(Source([teacher()]), destination, False, "teachers")
        self.assertEqual((destination.users, destination.courses), ([], []))

    def test_conflicting_course_does_not_adopt_or_enrol(self):
        from app.application.synchronization.courses import map_course
        source = Source([teacher()])
        destination = Moodle()
        destination.courses = [{"id": 20, "shortname": map_course(source.teaching_catalog()[0])["shortname"]}]
        result = synchronize(source, destination, False, "teachers")
        self.assertEqual(result["cursos"]["resumo"]["erro"], 1)
        self.assertEqual(result["vinculos"]["resumo"]["erro"], 1)
        self.assertEqual(result["professores"][0]["docencia"], "erro")
        self.assertEqual(destination.enrol_calls, 0)

    def test_enrol_failure_can_be_retried_without_duplicate_user_or_course(self):
        destination = Moodle()
        with patch.object(destination, "enrol_teacher", side_effect=IntegrationError("Sem permissão")):
            first = synchronize(Source([teacher()]), destination, False, "teachers")
        second = synchronize(Source([teacher()]), destination, False, "teachers")
        self.assertEqual(first["vinculos"]["resumo"]["erro"], 1)
        self.assertEqual(second["vinculos"]["resumo"]["vinculado"], 1)
        self.assertEqual((len(destination.users), len(destination.courses)), (1, 1))

    def test_duplicate_teacher_links_only_enrol_once(self):
        row = teacher()
        row["vinculos"] *= 2
        destination = Moodle()
        result = synchronize(Source([row]), destination, False, "teachers")
        self.assertEqual(result["vinculos"]["total"], 1)
        self.assertEqual(destination.enrol_calls, 1)

    def test_no_false_confirmation_when_role_is_not_returned(self):
        destination = Moodle()
        destination.course_teachers = lambda _: set()
        result = synchronize(Source([teacher()]), destination, False, "teachers")
        self.assertEqual(result["vinculos"]["resumo"]["erro"], 1)


class TeachingClientTests(unittest.TestCase):
    def test_catalog_is_read_from_legacy_api_and_filters_deleted(self):
        source = IEducarClient(SETTINGS)
        with patch.object(source, "get", side_effect=[
            {"turmas": [{"id": "10", "nome": "Turma A", "ano": "2026", "escola_id": "1", "deleted_at": None},
                        {"id": "11", "deleted_at": "2026-01-01"}]},
            {"options": {"2": "Matemática"}},
        ]) as get:
            result = source.teaching_catalog()
        self.assertEqual(result[0]["disciplina_id"], 2)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args[1]["turma_id"], 10)

    def test_invalid_catalog_fails_closed(self):
        client = IEducarClient(SETTINGS)
        with patch.object(client, "get", return_value={"turmas": [{"id": 10, "nome": "A", "ano": 2025, "escola_id": 1, "deleted_at": None}]}):
            with self.assertRaises(IntegrationError):
                client.teaching_catalog()

    def test_course_query_envelope_and_exact_identity(self):
        client = MoodleClient(SETTINGS)
        with patch.object(client, "call", return_value={"courses": [{"id": 20, "idnumber": "origin"}], "warnings": []}):
            self.assertEqual(client.find_course("idnumber", "origin")[0]["id"], 20)
            with self.assertRaises(IntegrationError):
                client.find_course("idnumber", "other")

    def test_enrol_null_response_and_role_payload(self):
        client = MoodleClient(replace(SETTINGS, moodle_teacher_role_id=8))
        with patch.object(client, "call", return_value=None) as call:
            client.enrol_teacher(7, 20)
        self.assertEqual(call.call_args.args[0], "enrol_manual_enrol_users")
        self.assertEqual(call.call_args.args[1]["enrolments[0][roleid]"], 8)
        with patch.object(client, "call", return_value=[]):
            with self.assertRaises(IntegrationError):
                client.enrol_teacher(7, 20)

    def test_role_is_checked_in_course_context(self):
        client = MoodleClient(SETTINGS)
        with patch.object(client, "call", return_value=[{"id": 7, "roles": [{"roleid": 3}]}, {"id": 8, "roles": [{"roleid": 5}]}]):
            self.assertEqual(client.course_teachers(20), {7})

    def test_setup_detects_missing_functions(self):
        client = MoodleClient(SETTINGS)
        with patch.object(client, "call", return_value={"functions": []}):
            with self.assertRaisesRegex(IntegrationError, "enrol_manual_enrol_users"):
                client.check_teaching_setup()

    def test_setup_accepts_configured_category_and_rejects_wrong_category(self):
        client = MoodleClient(SETTINGS)
        functions = ["core_user_get_users_by_field", "core_user_create_users", "core_course_get_categories",
                     "core_course_get_courses_by_field", "core_course_create_courses",
                     "core_enrol_get_enrolled_users", "enrol_manual_enrol_users"]
        info = {"functions": [{"name": f} for f in functions]}
        with patch.object(client, "call", side_effect=[info, [{"id": 1}]]):
            client.check_teaching_setup()
        with patch.object(client, "call", side_effect=[info, [{"id": 2}]]):
            with self.assertRaises(IntegrationError):
                client.check_teaching_setup()
