import unittest
from unittest.mock import MagicMock

from app.application.synchronization.courses import prepare_courses, synchronize_courses
from app.core.errors import IntegrationError
from app.application.synchronization.teachers import synchronize_teaching


def course(discipline=2):
    return {"instituicao_id": 1, "ano": 2026, "turma_id": 10,
            "disciplina_id": discipline, "turma_nome": "Turma A", "disciplina_nome": "Matemática"}


class CourseTests(unittest.TestCase):
    def test_duplicate_divergent_catalog_is_rejected(self):
        with self.assertRaises(IntegrationError):
            prepare_courses([course(), {**course(), "disciplina_nome": "Português"}])

    def test_dry_run_does_not_create_courses(self):
        destination = MagicMock()
        destination.find_course.return_value = []
        result = synchronize_courses(prepare_courses([course()]), destination, True)
        self.assertEqual(result[(10, 2)]["status"], "a_criar")
        destination.create_course.assert_not_called()
        destination.create.assert_not_called()

    def test_existing_course_is_not_recreated(self):
        destination = MagicMock()
        destination.find_course.return_value = [{"id": 20}]
        result = synchronize_courses(prepare_courses([course()]), destination, False)
        self.assertEqual(result[(10, 2)]["moodle_id"], 20)
        destination.create_course.assert_not_called()

    def test_creation_failure_does_not_block_other_courses(self):
        destination = MagicMock()
        destination.find_course.return_value = []
        destination.create_course.side_effect = [IntegrationError("Falha"), 21]
        result = synchronize_courses(prepare_courses([course(), course(3)]), destination, False)
        self.assertEqual(result[(10, 2)]["status"], "erro")
        self.assertEqual(result[(10, 3)]["status"], "criado")

    def test_teaching_uses_prepared_courses_without_synchronizing_them(self):
        destination = MagicMock()
        destination.find.return_value = [{"id": 7}]
        destination.course_teachers.return_value = {7}
        teacher = {"professor_id": 7, "vinculos": [{"turma_id": 10, "disciplina_id": 2}]}
        results = {(10, 2): {"status": "existente", "moodle_id": 20}}
        result = synchronize_teaching([teacher], results, destination, False)
        self.assertEqual(result["vinculos"]["resumo"]["existente"], 1)
        self.assertNotIn("cursos", result)
        destination.find_course.assert_not_called()
        destination.create_course.assert_not_called()
