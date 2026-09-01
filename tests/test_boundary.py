from __future__ import annotations

import ast
import os
import subprocess
import sys
from importlib.machinery import PathFinder
from pathlib import Path

import ast2python


def test_public_package_does_not_import_runtime_stack() -> None:
    root = Path(ast2python.__file__).resolve().parents[1]
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(root)!r}); "
        "import ast2python; "
        "assert 'pinelib' not in sys.modules; "
        "assert 'openpine_contracts' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_old_translation_api_is_physically_absent() -> None:
    for module in (
        "ast2python.binder",
        "ast2python.binder_model",
        "ast2python.binder_registry",
        "ast2python.translate_api",
        "ast2python.translator",
        "ast2python.profiles",
        "ast2python.openpine_compat",
    ):
        assert PathFinder.find_spec(module, list(ast2python.__path__)) is None, module
    assert "ast2python.profiles" not in sys.modules
    assert "ast2python.artifact" not in sys.modules
    assert not hasattr(ast2python, "translate_ast")
    assert not hasattr(ast2python, "Translator")


def test_rc5_environment_flag_cannot_restore_translation_api() -> None:
    root = Path(ast2python.__file__).resolve().parents[1]
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(root)!r}); "
        "import ast2python; "
        "assert not hasattr(ast2python, 'translate_ast'); "
        "assert 'ast2python.profiles' not in sys.modules; "
        "assert 'ast2python.artifact' not in sys.modules"
    )
    env = os.environ.copy()
    env["OPENPINE_RC5_COMPILER_COMPAT"] = "1"
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_no_production_module_uses_wildcard_imports() -> None:
    root = Path(ast2python.__file__).resolve().parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names), path
