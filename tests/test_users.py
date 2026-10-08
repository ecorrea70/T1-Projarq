import unittest
from unittest.mock import MagicMock, patch

from app.application.synchronization.orchestrator import synchronize
from app.application.accounts.mapping import map_identity, map_user
from app.application.accounts.synchronization import synchronize_users


class UserTests(unittest.TestCase):
    def test_identity_does_not_require_name_or_email(self):
        self.assertEqual(map_identity({"professor_id": 7}, "teachers"),
                         {"username": "ieducar-professor-7", "idnumber": "ieducar:professor:7"})

    def test_mapping_does_not_accept_invalid_identifier(self):
        for code in (None, True, -1, "7"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                map_identity({"aluno_id": code})

    def test_mapping_supports_both_profiles(self):
        for kind, label in (("students", "aluno"), ("teachers", "professor")):
            with self.subTest(kind=kind):
                mapped = map_user({f"{label}_id": 7, "nome": "Ana Silva", "email": "ana@example.com"}, kind)
                self.assertEqual(mapped["idnumber"], f"ieducar:{label}:7")
                self.assertEqual(mapped["username"], f"ieducar-{label}-7")

    def test_accounts_can_run_without_catalog_or_enrolment(self):
        destination = MagicMock()
        destination.find.return_value = []
        destination.create.return_value = 10
        result = synchronize_users([{"aluno_id": 7, "nome": "Ana Silva", "email": "ana@example.com"}], destination, False)
        self.assertEqual(result["resumo"]["criado"], 1)
        destination.create.assert_called_once()
        destination.find_course.assert_not_called()
        destination.enrol_students.assert_not_called()

    def test_dry_run_does_not_create_accounts(self):
        destination = MagicMock()
        destination.find.return_value = []
        result = synchronize_users([{"professor_id": 7, "nome": "Ana Silva", "email": "ana@example.com"}], destination, True, "teachers")
        self.assertEqual(result["resumo"]["a_criar"], 1)
        destination.create.assert_not_called()


class OrchestrationTests(unittest.TestCase):
    def test_dispatches_students_without_creating_courses(self):
        source, destination = MagicMock(), MagicMock()
        source.students.return_value = [{"id": 7}]
        source.teaching_catalog.return_value = [{"id": 10}]
        with patch("app.application.synchronization.orchestrator.synchronize_students", return_value={"ok": True}) as selected, \
                patch("app.application.synchronization.orchestrator.synchronize_courses") as courses:
            self.assertEqual(synchronize(source, destination, True), {"ok": True})
            selected.assert_called_once_with(source.students.return_value, source.teaching_catalog.return_value, destination, True)
            courses.assert_not_called()
        source.teachers.assert_not_called()

    def test_prepares_courses_before_dispatching_teachers(self):
        source, destination = MagicMock(), MagicMock()
        source.teachers.return_value = [{"professor_id": 7}]
        source.teaching_catalog.return_value = [{"id": 10}]
        prepared, results = {(10, 2): {}}, {(10, 2): {"status": "existente"}}
        with patch("app.application.synchronization.orchestrator.prepare_courses", return_value=prepared) as prepare, \
                patch("app.application.synchronization.orchestrator.validate_teacher_links") as validate, \
                patch("app.application.synchronization.orchestrator.synchronize_courses", return_value=results) as courses, \
                patch("app.application.synchronization.orchestrator.synchronize_teaching", return_value={"ok": True}) as teachers:
            result = synchronize(source, destination, True, "teachers")
            prepare.assert_called_once_with(source.teaching_catalog.return_value)
            validate.assert_called_once_with(source.teachers.return_value, prepared)
            destination.check_teaching_setup.assert_called_once()
            courses.assert_called_once_with(prepared, destination, True)
            teachers.assert_called_once_with(source.teachers.return_value, results, destination, True)
            self.assertEqual(result["cursos"]["resumo"]["existente"], 1)
        source.students.assert_not_called()

    def test_invalid_kind_does_not_read_origin(self):
        source = MagicMock()
        with self.assertRaises(ValueError):
            synchronize(source, MagicMock(), False, "invalid")
        self.assertEqual(source.mock_calls, [])
