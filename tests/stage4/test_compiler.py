from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ast2python import (
    BundleInvariantError,
    load_reference_target_manifest,
    verify_generated_artifact_v3,
    write_compilation_result,
)
from ast2python import (
    compile_reference_consumer_bundle as compile_consumer_bundle,
)
from ast2python.emission import emit_python_module, verify_source_map_v2
from ast2python.lowering import validate_lowering_plan

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "consumer"


class RecordingRuntime:
    def __init__(self, target: Any) -> None:
        self.target_manifest_hash = target.content_hash
        self.supported_operations = frozenset(target.operations)
        self.capabilities = target.capabilities
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("value_"):
            return 1.0
        if name.startswith("call_"):

            def invoke(*args: Any, **kwargs: Any) -> Any:
                self.calls.append(name)
                return args[-1] if args else None

            return invoke
        if name.startswith("op_"):

            def operation(*args: Any) -> Any:
                if "operator_binary" in name and len(args) == 3:
                    operator, left, right = args
                    return {
                        "+": left + right,
                        "-": left - right,
                        "*": left * right,
                        "/": left / right,
                        ">": left > right,
                        ">=": left >= right,
                        "<": left < right,
                        "<=": left <= right,
                        "==": left == right,
                        "!=": left != right,
                    }[operator]
                if "history" in name:
                    return args[0] if args else None
                return args[-1] if args else None

            return operation
        raise AttributeError(name)


def bundle(version: int) -> Path:
    return FIXTURES / f"pine-v{version}-consumer-bundle.json"


def test_all_six_versions_compile_to_exact_artifacts() -> None:
    target = load_reference_target_manifest()
    hashes: set[str] = set()
    for version in range(1, 7):
        result = compile_consumer_bundle(bundle(version), module_name=f"generated_v{version}")
        assert result.plan.pine_version == version
        assert len(result.plan.nodes) > 0
        assert set(result.plan.required_operations) <= set(target.operations)
        validate_lowering_plan(result.plan, target)
        verify_source_map_v2(
            result.emitted.source_map.to_dict(), expected_ir_ids=set(result.plan.nodes)
        )
        verify_generated_artifact_v3(
            result.artifact.payload, plan=result.plan, target=target, emitted=result.emitted
        )
        assert result.artifact.payload["version_context"]["pine_version"] == version
        proof = result.artifact.payload["projection_proof"]
        assert proof["mapped_ir_coverage"] is True
        assert proof["source_node_count"] == len(result.plan.dispositions)
        assert proof["ir_node_count"] == len(result.plan.nodes)
        hashes.add(result.emitted.code_hash)
    assert len(hashes) == 6


def test_generated_module_is_self_contained_and_runnable() -> None:
    target = load_reference_target_manifest()
    result = compile_consumer_bundle(bundle(2), module_name="generated_v2")
    namespace: dict[str, Any] = {}
    exec(compile(result.emitted.code, "generated_v2.py", "exec"), namespace)
    runtime = RecordingRuntime(target)
    output = namespace["GeneratedScript"](runtime).run()
    assert output is None
    assert runtime.calls == []
    assert "# Pine declaration (compile time only)" in result.emitted.code
    assert "ast2python" not in result.emitted.import_manifest
    assert "pine2ast" not in result.emitted.import_manifest


def test_generated_module_rejects_wrong_target() -> None:
    result = compile_consumer_bundle(bundle(6))
    namespace: dict[str, Any] = {}
    exec(result.emitted.code, namespace)

    class WrongRuntime:
        target_manifest_hash = "sha256:" + "0" * 64
        supported_operations = ()
        capabilities = ()

    with pytest.raises(RuntimeError, match="target manifest mismatch"):
        namespace["GeneratedScript"](WrongRuntime())


def test_compilation_is_byte_deterministic() -> None:
    first = compile_consumer_bundle(bundle(4), module_name="deterministic")
    second = compile_consumer_bundle(bundle(4), module_name="deterministic")
    assert first.plan.to_dict() == second.plan.to_dict()
    assert first.emitted.code == second.emitted.code
    assert first.emitted.source_map.to_dict() == second.emitted.source_map.to_dict()
    assert first.artifact.to_dict() == second.artifact.to_dict()


def test_write_compilation_result(tmp_path: Path) -> None:
    result = compile_consumer_bundle(bundle(5), module_name="written")
    paths = write_compilation_result(result, tmp_path)
    assert Path(paths["module"]).read_text(encoding="utf-8") == result.emitted.code
    assert json.loads(Path(paths["plan"]).read_text())["content_hash"] == result.plan.content_hash
    assert (
        json.loads(Path(paths["source_map"]).read_text())["content_hash"]
        == result.emitted.source_map.content_hash
    )
    assert (
        json.loads(Path(paths["artifact"]).read_text())["content_hash"]
        == result.artifact.payload["content_hash"]
    )


def test_unsafe_module_names_are_rejected() -> None:
    result = compile_consumer_bundle(bundle(6))
    target = load_reference_target_manifest()
    for value in ("bad-name", "../x", "x;import os", "1bad", "x y"):
        with pytest.raises(BundleInvariantError, match="A2P_EMIT_MODULE_NAME"):
            emit_python_module(result.plan, target, module_name=value)
