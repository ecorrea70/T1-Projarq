"""Protege os limites das camadas (MVC + Clean/SOLID) e a ausência de imports circulares."""
import ast
from pathlib import Path
import unittest


def imports():
    root = Path(__file__).resolve().parents[1]
    modules = {}
    for path in (root / "app").rglob("*.py"):
        parts = path.relative_to(root).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        dependencies = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module)
            elif isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
        modules[name] = dependencies
    return modules


class ArchitectureTests(unittest.TestCase):
    def test_layers_do_not_depend_on_outer_layers(self):
        forbidden = {
            "app.core": (
                "app.models",
                "app.views",
                "app.application",
                "app.infrastructure",
                "app.controllers",
                "app.api",
                "app.main",
            ),
            "app.models": (
                "app.views",
                "app.application",
                "app.infrastructure",
                "app.controllers",
                "app.api",
                "app.main",
            ),
            "app.views": (
                "app.models",
                "app.application",
                "app.infrastructure",
                "app.controllers",
                "app.api",
                "app.main",
            ),
            "app.application": (
                "app.infrastructure",
                "app.controllers",
                "app.api",
                "app.main",
            ),
            "app.infrastructure": (
                "app.views",
                "app.application",
                "app.controllers",
                "app.api",
                "app.main",
            ),
            "app.controllers": (
                "app.api",
                "app.main",
            ),
        }
        for module, dependencies in imports().items():
            for layer, blocked in forbidden.items():
                if module == layer or module.startswith(layer + "."):
                    for dependency in dependencies:
                        with self.subTest(module=module, dependency=dependency):
                            self.assertFalse(
                                any(
                                    dependency == target or dependency.startswith(target + ".")
                                    for target in blocked
                                )
                            )

    def test_import_graph_has_no_cycles(self):
        modules = imports()
        visited, visiting = set(), set()

        def visit(module):
            self.assertNotIn(module, visiting, f"Import circular em {module}")
            if module in visited:
                return
            visiting.add(module)
            for dependency in modules[module]:
                if dependency in modules:
                    visit(dependency)
            visiting.remove(module)
            visited.add(module)

        for module in modules:
            visit(module)

    def test_mvc_and_solid_components_exist(self):
        from app.controllers.sync_controller import SyncAuthGuard, SyncController, SyncExecutionLock
        from app.models.account import AccountIdentity, UserAccountModel
        from app.models.course import CourseModel
        from app.views.sync_view import accounts_report_view, conflict_view, health_view, report_view, summary_view
        from app.application.synchronization.orchestrator import STRATEGIES, StudentSyncStrategy, TeacherSyncStrategy

        self.assertIn("students", STRATEGIES)
        self.assertIn("teachers", STRATEGIES)
        self.assertIsInstance(STRATEGIES["students"], StudentSyncStrategy)
        self.assertIsInstance(STRATEGIES["teachers"], TeacherSyncStrategy)
        self.assertEqual(health_view(), {"status": "ok"})
        self.assertTrue(callable(SyncController().handle_sync))
        self.assertTrue(callable(SyncAuthGuard.verify))
        self.assertTrue(hasattr(SyncExecutionLock, "__enter__"))
        self.assertTrue(hasattr(AccountIdentity, "to_dict"))
        self.assertTrue(hasattr(UserAccountModel, "to_dict"))
        self.assertTrue(hasattr(CourseModel, "to_dict"))
        self.assertTrue(callable(report_view))
        self.assertTrue(callable(accounts_report_view))
        self.assertTrue(callable(conflict_view))
        self.assertTrue(callable(summary_view))
