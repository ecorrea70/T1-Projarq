import unittest
import os
from unittest.mock import patch

from app.clients import IEducarClient, IntegrationError, MoodleClient
from app.config import ConfigurationError, Settings
from app.sync import synchronize
from app.teaching import map_course
import test_sync
from test_sync import Moodle, SETTINGS, Source, student


def enrolled_student(code=1, classroom=10):
    return {**student(code, f"aluno{code}@escola.edu.br"),
            "turmas": [{"turma_id": classroom, "ano": 2026, "escola_id": 1}]}


def catalog():
    base = {"instituicao_id": 1, "escola_id": 1, "ano": 2026, "turma_nome": "A"}
    return [{**base, "turma_id": t, "disciplina_id": d, "disciplina_nome": n}
            for t in (10, 11) for d, n in ((2, "Matemática"), (3, "História"))]


def setup(rows):
    source = Source(rows)
    source.teaching_catalog = catalog
    destination = Moodle()
    destination.courses = [{**map_course(r), "id": 20 + i} for i, r in enumerate(catalog())]
    return source, destination


class EnrollmentTests(unittest.TestCase):
    def test_only_correct_class_courses_and_repeat(self):
        source, destination = setup([enrolled_student(1, 10), enrolled_student(2, 11)])
        first = synchronize(source, destination, False)
        self.assertEqual(first["vinculos"]["resumo"]["vinculado"], 4)
        self.assertEqual(destination.student_enrolled, {20: {10}, 21: {10}, 22: {11}, 23: {11}})
        second = synchronize(source, destination, False)
        self.assertEqual(second["vinculos"]["resumo"]["existente"], 4)
        self.assertEqual(destination.student_enrol_calls, 4)
        self.assertEqual(len(destination.users), 2)

    def test_dry_run_never_writes(self):
        source, destination = setup([enrolled_student()])
        result = synchronize(source, destination, True)
        self.assertEqual(result["vinculos"]["resumo"]["a_vincular"], 2)
        self.assertEqual((destination.users, destination.student_enrolled), ([], {}))

    def test_students_are_batched_per_course_and_teacher_role_is_preserved(self):
        source, destination = setup([enrolled_student(i) for i in range(1, 11)])
        destination.enrolled = {20: {900}}
        result = synchronize(source, destination, False)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 20)
        self.assertEqual(destination.student_enrol_calls, 2)
        self.assertEqual(destination.enrolled, {20: {900}})

    def test_existing_user_without_email_can_be_enrolled(self):
        source, destination = setup([{**enrolled_student(), "email": None}])
        destination.users = [{"id": 8, "idnumber": "ieducar:aluno:1"}]
        result = synchronize(source, destination, False)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 2)

    def test_multiple_classes_and_duplicate_links_deduplicate(self):
        row = enrolled_student()
        row["turmas"] += row["turmas"] + [{"turma_id": 11, "ano": 2026, "escola_id": 1}]
        source, destination = setup([row])
        self.assertEqual(synchronize(source, destination, False)["vinculos"]["total"], 4)

    def test_unknown_class_aborts_before_any_write(self):
        source, destination = setup([enrolled_student(classroom=99)])
        with self.assertRaises(IntegrationError):
            synchronize(source, destination, False)
        self.assertEqual(destination.users, [])

    def test_missing_course_is_not_adopted_or_created(self):
        source, destination = setup([enrolled_student()])
        destination.courses = destination.courses[1:]
        result = synchronize(source, destination, False)
        self.assertEqual(result["vinculos"]["resumo"]["erro"], 1)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 1)
        self.assertEqual(result["alunos"][0]["matricula"], "erro")
        self.assertEqual(len(destination.courses), 3)

    def test_failed_enrolment_is_retryable(self):
        source, destination = setup([enrolled_student()])
        with patch.object(destination, "enrol_students", side_effect=IntegrationError("Sem permissão")):
            first = synchronize(source, destination, False)
        self.assertEqual(first["vinculos"]["resumo"]["erro"], 2)
        self.assertEqual(synchronize(source, destination, False)["vinculos"]["resumo"]["vinculado"], 2)
        self.assertEqual(len(destination.users), 1)

    def test_notification_failure_after_commit_is_reconciled(self):
        source, destination = setup([enrolled_student()])
        original = destination.enrol_students
        def enrol_then_fail(user_ids, course_id):
            original(user_ids, course_id)
            raise IntegrationError("Falha de notificação")
        destination.enrol_students = enrol_then_fail
        result = synchronize(source, destination, False)
        self.assertEqual(result["vinculos"]["resumo"]["vinculado"], 2)
        self.assertTrue(all("aviso" in r for r in result["vinculos"]["resultados"]))
        self.assertEqual(result["alunos"][0]["matricula"], "confirmada")

    def test_no_false_confirmation(self):
        source, destination = setup([enrolled_student()])
        destination.course_students = lambda _: set()
        self.assertEqual(synchronize(source, destination, False)["vinculos"]["resumo"]["erro"], 2)

    def test_no_active_class_reports_no_class(self):
        source, destination = setup([student()])
        result = synchronize(source, destination, False)
        self.assertEqual(result["alunos"][0]["matricula"], "sem_turma")
        self.assertEqual(destination.student_enrol_calls, 0)


def enrollment(registration=101, classroom=10, **changes):
    return {"ref_cod_matricula": registration, "ref_cod_turma": classroom, "ativo": 1,
            "transferido": None, "remanejado": None, "abandono": None, "falecido": None,
            "reclassificado": None, "data_exclusao": None, **changes}


class StudentEnrollmentClientTests(unittest.TestCase):
    def test_history_flags_and_inactive_links_are_ignored(self):
        client = IEducarClient(SETTINGS)
        row = test_sync.ClientTests.registration()
        row["enrollments"] = [enrollment(), enrollment(), enrollment(classroom=11, ativo=0),
                              enrollment(classroom=12, transferido=True), enrollment(classroom=13, remanejado=True)]
        with patch.object(client, "get", return_value=test_sync.ClientTests.page([row])):
            self.assertEqual(client.students()[0]["turmas"], [{"turma_id": 10, "ano": 2026, "escola_id": 1}])

    def test_different_registrations_of_same_student_merge_classes(self):
        client = IEducarClient(SETTINGS)
        first = test_sync.ClientTests.registration()
        first["enrollments"] = [enrollment()]
        second = {**first, "id": 202, "enrollments": [enrollment(registration=202, classroom=11)]}
        with patch.object(client, "get", return_value=test_sync.ClientTests.page([first, second])):
            self.assertEqual([r["turma_id"] for r in client.students()[0]["turmas"]], [10, 11])

    def test_missing_or_mismatched_enrollment_fails_closed(self):
        client = IEducarClient(SETTINGS)
        for links in (None, [enrollment(registration=999)], [{"ref_cod_matricula": 101, "ativo": 1}]):
            row = {**test_sync.ClientTests.registration(), "enrollments": links}
            with patch.object(client, "get", return_value=test_sync.ClientTests.page([row])):
                with self.assertRaises(IntegrationError):
                    client.students()

    def test_batch_uses_student_role(self):
        client = MoodleClient(SETTINGS)
        with patch.object(client, "call", return_value=None) as call:
            client.enrol_students([7, 8], 20)
        params = call.call_args.args[1]
        self.assertEqual(params["enrolments[0][roleid]"], 5)
        self.assertEqual(params["enrolments[1][userid]"], 8)
        self.assertEqual(params["enrolments[1][courseid]"], 20)


class EnrollmentConfigurationTests(unittest.TestCase):
    def environment(self):
        return {"IEDUCAR_URL": "http://localhost", "IEDUCAR_TOKEN": "rest", "IEDUCAR_ACCESS_KEY": "legacy",
                "IEDUCAR_INSTITUTION_ID": "1", "IEDUCAR_SCHOOL_ID": "1", "IEDUCAR_YEAR": "2026",
                "MOODLE_URL": "http://localhost:8080", "MOODLE_TOKEN": "test"}

    def test_role_must_be_explicit_before_student_enrolment(self):
        with patch.dict(os.environ, self.environment(), clear=True):
            with self.assertRaisesRegex(ConfigurationError, "MOODLE_STUDENT_ROLE_ID"):
                Settings.from_env()

    def test_students_do_not_require_course_creation_settings(self):
        with patch.dict(os.environ, {**self.environment(), "MOODLE_STUDENT_ROLE_ID": "5",
                                     "MOODLE_CATEGORY_ID": "", "MOODLE_TEACHER_ROLE_ID": ""}, clear=True):
            self.assertEqual(Settings.from_env().moodle_student_role_id, 5)

    def test_non_positive_student_role_is_rejected(self):
        for role in ("0", "-1"):
            with patch.dict(os.environ, {**self.environment(), "MOODLE_STUDENT_ROLE_ID": role}, clear=True):
                with self.assertRaises(ConfigurationError):
                    Settings.from_env()
