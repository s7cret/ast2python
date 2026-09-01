from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ast2python import (
    compile_consumer_bundle,
    inspect_consumer_bundle,
    load_pinelib_target_manifest,
    validate_consumer_bundle,
)
from ast2python.compiler import write_compilation_result
from ast2python.mode import CompilationMode


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    del as_json
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_validate(path: str, *, analysis: bool, as_json: bool) -> int:
    mode = CompilationMode.ANALYSIS if analysis else CompilationMode.PRODUCTION
    report = validate_consumer_bundle(Path(path), mode=mode)
    payload = report.to_dict()
    _print_payload(payload, as_json=as_json)
    return 0 if report.ok else 1


def run_inspect(path: str, *, as_json: bool) -> int:
    payload = inspect_consumer_bundle(Path(path))
    _print_payload(payload, as_json=as_json)
    return 0


def run_compile(
    path: str,
    *,
    output: str,
    module_name: str,
    target_manifest: str,
    as_json: bool,
) -> int:
    target = load_pinelib_target_manifest(target_manifest)
    result = compile_consumer_bundle(Path(path), target=target, module_name=module_name)
    paths = write_compilation_result(result, output)
    payload = {"ok": True, "summary": result.to_summary(), "files": paths}
    _print_payload(payload, as_json=as_json)
    return 0
