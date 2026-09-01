from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from ast2python import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python.emission import emit_python_module
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_reference_target_manifest

_SENSITIVE_KEY = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|API_KEY|ACCESS_KEY)", re.I
)


def _embedded_sensitive_environment_values(code: str) -> list[str]:
    leaked: list[str] = []
    for key, value in os.environ.items():
        if not _SENSITIVE_KEY.search(key) or len(value) < 8:
            continue
        if value in code:
            leaked.append(key)
    return sorted(leaked)


def run_security_gate(bundle_path: str | Path) -> dict[str, Any]:
    result = compile_consumer_bundle(Path(bundle_path))
    findings: list[dict[str, str]] = []
    tree = ast.parse(result.emitted.code)
    forbidden_calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {
            "eval",
            "exec",
            "compile",
            "__import__",
        }:
            forbidden_calls.add(node.func.id)
    if forbidden_calls:
        findings.append(
            {"code": "FORBIDDEN_DYNAMIC_EXECUTION", "detail": repr(sorted(forbidden_calls))}
        )
    imports = set(result.emitted.import_manifest)
    if any(
        item.split(".", 1)[0] in {"ast2python", "pine2ast", "subprocess", "pickle"}
        for item in imports
    ):
        findings.append({"code": "FORBIDDEN_IMPORT", "detail": repr(sorted(imports))})
    target = load_reference_target_manifest()
    for unsafe in ("bad-name", "x;import os", "../x", "x y", "1bad", "x\nimport os"):
        try:
            emit_python_module(result.plan, target, module_name=unsafe)
        except BundleInvariantError:
            pass
        else:
            findings.append({"code": "MODULE_NAME_INJECTION", "detail": unsafe})
    leaked = _embedded_sensitive_environment_values(result.emitted.code)
    if leaked:
        findings.append({"code": "ENVIRONMENT_SECRET_LEAK", "detail": repr(leaked)})
    return {
        "schema_id": "ast2python.stage4.security.v1",
        "ok": not findings,
        "findings": findings,
        "import_manifest": list(result.emitted.import_manifest),
        "environment_keys_embedded": leaked,
        "sensitive_environment_keys_embedded": leaked,
    }
