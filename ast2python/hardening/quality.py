from __future__ import annotations

import ast
import compileall
import importlib.util
import shutil
import tabnanny
from pathlib import Path
from typing import Any

_CORE_PREFIXES = ("admission", "lowering", "emission", "artifacts", "compiler.py")


def _is_core(relative: str) -> bool:
    return relative.startswith(_CORE_PREFIXES)


def run_quality_gate(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    package = root_path / "ast2python"
    findings: list[dict[str, Any]] = []
    module_sizes: dict[str, int] = {}
    broad_except: list[str] = []
    ignore_errors: list[str] = []
    syntax_ok = True
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        text = path.read_text(encoding="utf-8")
        module_sizes[relative] = len(text.splitlines())
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            syntax_ok = False
            findings.append({"code": "SYNTAX", "path": relative, "detail": str(exc)})
            continue
        if _is_core(relative):
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is not None:
                    if isinstance(node.type, ast.Name) and node.type.id in {
                        "Exception",
                        "BaseException",
                    }:
                        broad_except.append(f"{relative}:{node.lineno}")
            if "mypy: ignore-errors" in text:
                ignore_errors.append(relative)
        if module_sizes[relative] > 700:
            findings.append(
                {"code": "OVERSIZED_MODULE", "path": relative, "lines": module_sizes[relative]}
            )
    if broad_except:
        findings.append({"code": "BROAD_EXCEPT_CORE", "paths": broad_except})
    if ignore_errors:
        findings.append({"code": "MYPY_IGNORE_ERRORS_CORE", "paths": ignore_errors})
    compile_ok = compileall.compile_dir(str(package), quiet=1, force=True)
    try:
        tabnanny.check(str(package))
        tabnanny_ok = True
    except Exception as exc:  # tabnanny has no stable dedicated exception type
        tabnanny_ok = False
        findings.append({"code": "TABNANNY", "detail": str(exc)})
    tools = {
        name: (
            "AVAILABLE" if shutil.which(name) or importlib.util.find_spec(name) else "NOT_AVAILABLE"
        )
        for name in ("ruff", "black", "mypy")
    }
    return {
        "schema_id": "ast2python.stage4.quality.v1",
        "ok": not findings and syntax_ok and compile_ok and tabnanny_ok,
        "compileall": "PASS" if compile_ok else "FAIL",
        "tabnanny": "PASS" if tabnanny_ok else "FAIL",
        "ruff": tools["ruff"],
        "black": tools["black"],
        "mypy": tools["mypy"],
        "module_sizes": dict(sorted(module_sizes.items())),
        "findings": findings,
    }
