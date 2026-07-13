import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_context", ROOT / "analytics" / "runtime_context.py")
runtime_context = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime_context)


class RuntimeWorkspaceIsolationTests(unittest.TestCase):
    def test_shared_data_directory_is_rejected(self):
        with self.assertRaises(runtime_context.RuntimeContextError):
            runtime_context.require_absolute_directory(ROOT / "data", "runtime root")

    def test_contained_workspace_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "inputs" / "original" / "dengue.csv"
            self.assertEqual(runtime_context.require_within(workspace, candidate, "input"), candidate.resolve())

    def test_traversal_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve() / "workspace"
            workspace.mkdir()
            with self.assertRaises(runtime_context.RuntimeContextError):
                runtime_context.require_within(workspace, workspace / ".." / "escaped.csv", "input")

    def test_runtime_route_uses_fixed_server_filenames_and_no_shell(self):
        route = (ROOT / "app" / "api" / "runtime" / "validate" / "route.ts").read_text(encoding="utf-8")
        self.assertIn('storedName: "dengue.csv"', route)
        self.assertIn('storedName: "climate.csv"', route)
        self.assertIn('shell: false', route)
        self.assertIn('export const runtime = "nodejs"', route)


if __name__ == "__main__":
    unittest.main()
