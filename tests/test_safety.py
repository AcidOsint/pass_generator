"""Static checks over the package source: no network, no `random`, no file writes."""

import ast
import pathlib
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "q3pass"

FORBIDDEN_MODULES = {
    "random", "socket", "urllib", "http", "ssl", "requests",
    "subprocess", "logging", "pickle", "shelve", "sqlite3",
}


def sources():
    files = sorted(PACKAGE.glob("*.py"))
    assert files, "package sources not found"
    for path in files:
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module.split(".")[0]


def calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                yield func.id
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                yield f"{func.value.id}.{func.attr}"


class SafetyTests(unittest.TestCase):
    def test_no_forbidden_imports(self):
        for path, tree in sources():
            bad = set(imported_modules(tree)) & FORBIDDEN_MODULES
            self.assertFalse(bad, f"{path.name} imports {bad}")

    def test_no_file_or_shell_calls(self):
        for path, tree in sources():
            used = set(calls(tree))
            for name in ("open", "os.system", "os.popen", "io.open"):
                self.assertNotIn(name, used, f"{path.name} calls {name}")

    def test_secrets_only_in_generator(self):
        for path, tree in sources():
            if "secrets" in set(imported_modules(tree)):
                self.assertEqual(path.name, "generator.py")

    def test_generator_has_no_output(self):
        tree = ast.parse((PACKAGE / "generator.py").read_text(encoding="utf-8"))
        self.assertNotIn("print", set(calls(tree)))
        self.assertNotIn("input", set(calls(tree)))
        self.assertFalse({"sys", "os"} & set(imported_modules(tree)))


if __name__ == "__main__":
    unittest.main()
