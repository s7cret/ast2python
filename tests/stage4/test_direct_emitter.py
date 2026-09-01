from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ast2python import (
    BundleInvariantError,
    load_reference_target_manifest,
)
from ast2python import (
    compile_consumer_bundle as compile_production_bundle,
)
from ast2python import (
    compile_reference_consumer_bundle as compile_consumer_bundle,
)
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.emission import verify_source_map_v2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "consumer"
CORPUS_MANIFEST = Path(__file__).resolve().parents[1] / "corpus" / "manifest.json"


def test_generated_module_is_structural_and_contains_no_ir_interpreter() -> None:
    result = compile_consumer_bundle(
        FIXTURES / "pine-v2-consumer-bundle.json",
        module_name="structural_v2",
    )

    forbidden = ("PLAN_NODES", "def _eval", "execute_operation", "execute_lazy_operation")
    assert all(marker not in result.emitted.code for marker in forbidden)

    tree = ast.parse(result.emitted.code)
    summary = result.emitted.to_summary()
    assert summary["module_name"] == "structural_v2"
    assert summary["line_count"] == len(result.emitted.code.splitlines())
    assert any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in ast.walk(tree))
    assert any(
        isinstance(node, ast.FunctionDef) and node.name.startswith("udf_")
        for node in ast.walk(tree)
    )
    assert any(isinstance(node, ast.If) for node in ast.walk(tree))
    assert any(isinstance(node, ast.For) for node in ast.walk(tree))


def test_reference_target_has_exact_call_bindings_for_normative_corpus() -> None:
    target = load_reference_target_manifest()
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    required: set[tuple[str, str, str]] = set()
    for case in manifest["cases"]:
        bundle = json.loads(
            (Path(__file__).resolve().parents[2] / case["consumer_bundle"]).read_text(
                encoding="utf-8"
            )
        )
        for call in bundle["semantic_facts"]["calls"]:
            symbol_id = call["symbol_id"]
            if symbol_id.startswith("user:function:"):
                continue
            required.add((symbol_id, call["overload_id"], call["call_form"]))

    assert required
    assert required <= set(target.call_bindings)
    assert all(binding.python_name.isidentifier() for binding in target.call_bindings.values())


def test_missing_exact_call_binding_fails_before_emission() -> None:
    target = load_reference_target_manifest()
    runtime_bundle = (
        Path(__file__).resolve().parents[1] / "corpus" / "v6" / "v6-user-function.bundle.json"
    )
    bundle = json.loads(runtime_bundle.read_text(encoding="utf-8"))
    call = next(
        row
        for row in bundle["semantic_facts"]["calls"]
        if row["symbol_id"] not in {"pine:function:indicator", "pine:function:study"}
        and not row["symbol_id"].startswith("user:function:")
    )
    key = (call["symbol_id"], call["overload_id"], call["call_form"])
    reduced = target.without_call_binding(key)

    with pytest.raises(BundleInvariantError, match="A2P_TARGET_CALL_BINDING"):
        compile_production_bundle(
            runtime_bundle,
            target=reduced,
        )


def test_generated_udf_body_runs_only_when_called() -> None:
    target = load_reference_target_manifest()
    result = compile_production_bundle(
        Path(__file__).resolve().parents[1] / "corpus" / "v6" / "v6-user-function.bundle.json",
        target=target,
        module_name="structural_udf",
    )
    namespace: dict[str, Any] = {}
    exec(compile(result.emitted.code, "<structural_udf>", "exec"), namespace)

    class Runtime:
        target_manifest_hash = target.content_hash
        supported_operations = frozenset(target.operations)
        capabilities = target.capabilities

        def __init__(self) -> None:
            self.calls: list[str] = []

        def __getattr__(self, name: str) -> Any:
            if name.startswith("call_"):

                def invoke(*args: Any, **kwargs: Any) -> Any:
                    self.calls.append(name)
                    return 1.0

                return invoke
            if name.startswith("value_"):
                return 1.0
            if name.startswith("op_"):

                def operation(*args: Any, **kwargs: Any) -> Any:
                    return args[0] if args else None

                return operation
            raise AttributeError(name)

    runtime = Runtime()
    script = namespace["GeneratedScript"](runtime)
    assert runtime.calls == []
    script.run()
    assert runtime.calls


def test_direct_emitter_source_map_uses_executable_ranges() -> None:
    result = compile_consumer_bundle(
        FIXTURES / "pine-v6-consumer-bundle.json",
        module_name="range_map",
    )
    entries = result.emitted.source_map.to_dict()["entries"]
    expected_fields = {
        "python_start",
        "python_end",
        "source_node_id",
        "source_span",
        "ir_id",
        "origin",
        "semantic_rule_ids",
    }
    assert entries
    assert all(set(entry) == expected_fields for entry in entries)
    assert {entry["ir_id"] for entry in entries if entry["ir_id"] is not None} >= set(
        result.plan.nodes
    )
    lines = result.emitted.code.splitlines()
    for entry in entries:
        start = entry["python_start"]
        end = entry["python_end"]
        assert start["line"] > 0
        assert (end["line"], end["column"]) >= (start["line"], start["column"])
        if entry["origin"] == "PINE":
            assert entry["source_node_id"]
            assert "PLAN_NODES" not in lines[start["line"] - 1]


def _reseal_source_map(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return payload


@pytest.mark.parametrize(
    ("code", "mutate"),
    [
        (
            "A2P_SOURCE_MAP_RANGE",
            lambda entry: entry.__setitem__("python_end", {"line": 1, "column": 0}),
        ),
        (
            "A2P_SOURCE_MAP_POSITION",
            lambda entry: entry.__setitem__("python_start", {"line": 1}),
        ),
        ("A2P_SOURCE_MAP_ORIGIN", lambda entry: entry.__setitem__("origin", "UNKNOWN")),
        ("A2P_SOURCE_MAP_RULES", lambda entry: entry.__setitem__("semantic_rule_ids", [1])),
        (
            "A2P_SOURCE_MAP_SOURCE",
            lambda entry: entry.__setitem__("source_node_id", None),
        ),
    ],
)
def test_range_source_map_rejects_invalid_entries(code: str, mutate: Any) -> None:
    result = compile_consumer_bundle(FIXTURES / "pine-v6-consumer-bundle.json")
    payload = copy.deepcopy(result.emitted.source_map.to_dict())
    pine_entry = next(entry for entry in payload["entries"] if entry["origin"] == "PINE")
    mutate(pine_entry)
    with pytest.raises(BundleInvariantError, match=code):
        verify_source_map_v2(_reseal_source_map(payload))


def test_range_source_map_rejects_scaffold_with_fabricated_source() -> None:
    result = compile_consumer_bundle(FIXTURES / "pine-v6-consumer-bundle.json")
    payload = copy.deepcopy(result.emitted.source_map.to_dict())
    scaffold = next(entry for entry in payload["entries"] if entry["origin"] == "SCAFFOLD")
    scaffold["source_node_id"] = "fake"
    scaffold["source_span"] = {}
    with pytest.raises(BundleInvariantError, match="A2P_SOURCE_MAP_SCAFFOLD"):
        verify_source_map_v2(_reseal_source_map(payload))
