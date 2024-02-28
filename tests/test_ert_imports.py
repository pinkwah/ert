"""Test the import structure of the `_ert` module.

The rules are:
1. Modules in `_ert` are not allowed to import from `ert`
2. Modules in `_ert` can only import children or siblings
3. Imports in `_ert` make a DAG
4. Imports in a `TYPE_CHECKING` block or dynamically at runtime (within a
   function) are exceptions to these rules
"""

from __future__ import annotations

import ast
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from tests.utils import SOURCE_DIR


def assert_valid_name(name: str, module: str) -> None:
    if name.startswith("ert"):
        raise AssertionError(f"Module '{module}' must NOT import from 'ert'")


def path_to_module_name(path: Path) -> str:
    assert path.is_file()

    relpath = path.relative_to(SOURCE_DIR / "src")
    return f"{'.'.join(relpath.parts[:-1])}.{path.stem}"


def resolve_import_module_name(path: Path, module_name: str) -> str:
    if (match := re.match(r"^(\.+)(.+)$", module_name)) is None:
        # module_name doesn't start with .'s, so it's an absolute path already
        return module_name

    for _ in match[1]:
        path = path.parent

    parts = match[2].split(".")
    for part in parts[:-1]:
        path = path / part
    path = path / f"{parts[-1]}.py"
    assert path.exists(), f"{module_name} was resolved to {path}, which doesn't exist"

    return path_to_module_name(path)


class ImportChecker(ast.NodeVisitor):
    def __init__(self, imports: list[str], path: Path, module_name: str) -> None:
        super().__init__()

        self._imports = imports
        self._path = path
        self._module_name = module_name

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            name = resolve_import_module_name(self._path, alias.name)
            assert_valid_name(name, self._module_name)

            if name.startswith("_ert"):
                self._imports.append(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        name = resolve_import_module_name(self._path, node.module or "")
        assert_valid_name(name, self._module_name)

        if name.startswith("_ert"):
            self._imports.append(name)

    def visit_If(self, node: ast.If) -> None:
        """Allow imports in `if TYPE_CHECKING` blocks"""
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            return

        self.generic_visit(node)


@pytest.mark.parametrize(
    "name,body,error",
    [
        # No imports
        pytest.param("_ert.foo", "import os", None, id="no ert import"),
        # Importing `ert`
        pytest.param(
            "_ert.foo",
            "import ert",
            AssertionError,
            id="import ert",
        ),
        pytest.param(
            "_ert.foo",
            "if TYPE_CHECKING: import ert",
            None,
            id="import ert in type hints",
        ),
        pytest.param(
            "_ert.foo",
            "if some_other_condition: import ert",
            AssertionError,
            id="top-level conditional ert import",
        ),
        pytest.param(
            "_ert.foo",
            "from ert import foo",
            AssertionError,
            id="from ert import",
        ),
        pytest.param(
            "_ert.foo",
            "if TYPE_CHECKING: from ert import foo",
            None,
            id="from ert import in type hints",
        ),
        pytest.param(
            "_ert.foo",
            "if some_other_condition: from ert import foo",
            AssertionError,
            id="top-level conditional from ert import",
        ),
        # Importing `_ert`
        pytest.param(
            "_ert.foo",
            "import _ert.foo.bar",
            None,
            id="import child",
        ),
        pytest.param(
            "_ert.foo",
            "from . import bar",
            None,
            id="import child relatively",
        ),
        pytest.param(
            "_ert.foo",
            "import _ert.bar",
            None,
            id="import sibling",
        ),
        pytest.param(
            "_ert.foo",
            "from .bar import foo",
            None,
            id="import sibling relatively",
        ),
        pytest.param(
            "_ert.foo.bar",
            "import _ert.foo",
            AssertionError,
            id="import parent",
        ),
        pytest.param(
            "_ert.foo.bar",
            "from ..foo import bar",
            AssertionError,
            id="import parent relatively",
        ),
    ],
)
def test_sanity(name, body, error) -> None:
    """Ensure that this test behaves as intended"""
    ctx = pytest.raises(error) if error else ExitStack()

    module = ast.parse(body, name)
    checker = ImportChecker([], Path(name), name)
    with ctx:
        checker.visit(module)


def test_check_imports(source_root) -> None:
    source_root = Path(source_root)
    import_map = {}
    for path in source_root.rglob("src/_ert/**/*.py"):
        with open(path) as f:
            module = ast.parse(f.read(), path.name)

        module_name = path_to_module_name(path)

        import_map[module_name] = []
        checker = ImportChecker(import_map[module_name], path, module_name)
        checker.visit(module)
