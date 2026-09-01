from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from ast2python import BundleInvariantError, load_reference_target_manifest
from ast2python import compile_reference_consumer_bundle as compile_consumer_bundle
from ast2python.admission.ast_view import StrictASTNode
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.admission.facts import SemanticFactView
from ast2python.artifacts import build_generated_artifact_v3, verify_generated_artifact_v3
from ast2python.emission import verify_source_map_v2
from ast2python.lowering import TargetManifest
from ast2python.lowering.recipes import select_recipe

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "fixtures" / "consumer" / "pine-v6-consumer-bundle.json"


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(value)
    value.pop("content_hash", None)
    value["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return value


def _assert_code(code: str, fn) -> None:
    with pytest.raises(BundleInvariantError) as captured:
        fn()
    assert captured.value.finding.code == code


def test_source_map_defensive_branches() -> None:
    result = compile_consumer_bundle(BUNDLE)
    base = result.emitted.source_map.to_dict()
    mapped_indexes = [
        index for index, entry in enumerate(base["entries"]) if entry["ir_id"] is not None
    ]
    assert len(mapped_indexes) >= 2
    cases: list[tuple[str, Any]] = []

    mutated = copy.deepcopy(base)
    mutated["extra"] = 1
    cases.append(("A2P_SOURCE_MAP_FIELDS", mutated))
    mutated = copy.deepcopy(base)
    mutated["schema_version"] = "9"
    cases.append(("A2P_SOURCE_MAP_SCHEMA", mutated))
    mutated = copy.deepcopy(base)
    mutated["content_hash"] = "sha256:" + "0" * 64
    cases.append(("A2P_SOURCE_MAP_HASH", mutated))
    mutated = copy.deepcopy(base)
    mutated["entries"] = {}
    cases.append(("A2P_SOURCE_MAP_ENTRIES", _seal(mutated)))
    mutated = copy.deepcopy(base)
    mutated["entries"][0]["extra"] = 1
    cases.append(("A2P_SOURCE_MAP_ENTRY", _seal(mutated)))
    mutated = copy.deepcopy(base)
    mutated["entries"][mapped_indexes[1]]["ir_id"] = mutated["entries"][mapped_indexes[0]]["ir_id"]
    cases.append(("A2P_SOURCE_MAP_IR", _seal(mutated)))
    mutated = copy.deepcopy(base)
    mutated["entries"][0]["python_start"]["line"] = 0
    cases.append(("A2P_SOURCE_MAP_POSITION", _seal(mutated)))
    pine_index = next(
        index for index, entry in enumerate(base["entries"]) if entry["origin"] == "PINE"
    )
    mutated = copy.deepcopy(base)
    mutated["entries"][pine_index]["source_span"] = []
    cases.append(("A2P_SOURCE_MAP_SPAN", _seal(mutated)))

    for code, payload in cases:
        _assert_code(code, lambda payload=payload: verify_source_map_v2(payload))
    _assert_code(
        "A2P_SOURCE_MAP_COVERAGE",
        lambda: verify_source_map_v2(base, expected_ir_ids={"ir:not-present"}),
    )


def test_target_manifest_defensive_branches() -> None:
    base = load_reference_target_manifest().to_dict()
    cases: list[tuple[str, Any]] = []
    mutated = copy.deepcopy(base)
    mutated["extra"] = 1
    cases.append(("A2P_TARGET_FIELDS", mutated))
    mutated = copy.deepcopy(base)
    mutated["schema_version"] = "9"
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_SCHEMA", mutated))
    mutated = copy.deepcopy(base)
    mutated["operations"] = {}
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_OPERATIONS", mutated))
    mutated = copy.deepcopy(base)
    mutated["operations"][0]["extra"] = 1
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_OPERATION", mutated))
    mutated = copy.deepcopy(base)
    mutated["operations"][1]["name"] = mutated["operations"][0]["name"]
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_OPERATION_ID", mutated))
    mutated = copy.deepcopy(base)
    mutated["operations"][0]["evaluation"] = "guess"
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_EVALUATION", mutated))
    mutated = copy.deepcopy(base)
    mutated["operations"][0]["effect"] = "guess"
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_EFFECT", mutated))
    mutated = copy.deepcopy(base)
    mutated["capabilities"] = [1]
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_CAPABILITIES", mutated))
    mutated = copy.deepcopy(base)
    mutated["allowed_imports"] = [1]
    mutated = _seal(mutated)
    cases.append(("A2P_TARGET_IMPORTS", mutated))
    mutated = copy.deepcopy(base)
    mutated["content_hash"] = "sha256:" + "0" * 64
    cases.append(("A2P_TARGET_HASH", mutated))
    for code, payload in cases:
        _assert_code(code, lambda payload=payload: TargetManifest.from_mapping(payload))


def test_artifact_commit_and_optional_verification_branches() -> None:
    result = compile_consumer_bundle(BUNDLE)
    target = load_reference_target_manifest()
    with pytest.raises(BundleInvariantError, match="A2P_ARTIFACT_COMMIT"):
        build_generated_artifact_v3(
            bundle_hash=result.plan.bundle_hash,
            source_hash=result.artifact.payload["source_hash"],
            version_context=result.artifact.payload["version_context"],
            plan=result.plan,
            target=target,
            emitted=result.emitted,
            producer_commit="bad",
        )
    # The artifact is independently valid even when comparison objects are absent.
    verify_generated_artifact_v3(result.artifact.payload)


def _node(kind: str, **fields: Any) -> StrictASTNode:
    return StrictASTNode(
        node_id="n",
        kind=kind,
        span=MappingProxyType(
            {
                "start_offset": 0,
                "end_offset": 1,
                "start_line": 1,
                "start_col": 1,
                "end_line": 1,
                "end_col": 2,
            }
        ),
        fields=MappingProxyType(fields),
        child_node_ids=(),
    )


def _fact(kind: str, *, operator: str | None = None) -> SemanticFactView:
    raw = {} if operator is None else {"operator": operator}
    return SemanticFactView(
        node_id="n",
        node_kind=kind,
        classification="EXPRESSION",
        resolved_type=None,
        scope_id="scope:global",
        symbol_id=None,
        overload_id=None,
        call_form=None,
        receiver_type=None,
        coercions=(),
        semantic_rule_ids=(),
        stateful_call=False,
        raw=MappingProxyType(raw),
    )


def test_recipe_fail_closed_branches() -> None:
    _assert_code(
        "A2P_RECIPE_CALL_FACT",
        lambda: select_recipe(version=6, node=_node("CallExpr"), fact=_fact("CallExpr"), call=None),
    )
    _assert_code(
        "A2P_RECIPE_OPERATOR",
        lambda: select_recipe(
            version=6, node=_node("BinaryExpr"), fact=_fact("BinaryExpr"), call=None
        ),
    )
    _assert_code(
        "A2P_RECIPE_MISSING",
        lambda: select_recipe(
            version=6, node=_node("UnknownNode"), fact=_fact("UnknownNode"), call=None
        ),
    )


def _artifact_mutation(base: dict[str, Any], mutator) -> dict[str, Any]:
    candidate = copy.deepcopy(base)
    mutator(candidate)
    return _seal(candidate)


def test_artifact_deep_contract_branches() -> None:
    result = compile_consumer_bundle(BUNDLE)
    target = load_reference_target_manifest()
    base = result.artifact.to_dict()
    cases = [
        (
            "A2P_ARTIFACT_PRODUCER",
            _artifact_mutation(base, lambda d: d.__setitem__("producer", {})),
            {},
        ),
        (
            "A2P_ARTIFACT_VERSION",
            _artifact_mutation(base, lambda d: d.__setitem__("version_context", [])),
            {},
        ),
        (
            "A2P_ARTIFACT_ENTRYPOINT",
            _artifact_mutation(base, lambda d: d.__setitem__("entrypoint", {})),
            {},
        ),
        (
            "A2P_ARTIFACT_LIST",
            _artifact_mutation(base, lambda d: d.__setitem__("required_operations", [1])),
            {},
        ),
        (
            "A2P_ARTIFACT_IMPORT",
            _artifact_mutation(
                base,
                lambda d: d.__setitem__(
                    "import_manifest", sorted([*d["import_manifest"], "ast2python"])
                ),
            ),
            {},
        ),
        (
            "A2P_ARTIFACT_PROJECTION",
            _artifact_mutation(base, lambda d: d.__setitem__("projection_proof", {})),
            {},
        ),
        (
            "A2P_ARTIFACT_PROJECTION",
            _artifact_mutation(
                base, lambda d: d["projection_proof"].__setitem__("source_node_count", -1)
            ),
            {},
        ),
        (
            "A2P_ARTIFACT_RELEASE",
            _artifact_mutation(base, lambda d: d.__setitem__("release_acceptance", {})),
            {},
        ),
        (
            "A2P_ARTIFACT_LINEAGE",
            _artifact_mutation(base, lambda d: d.__setitem__("bundle_hash", "sha256:" + "1" * 64)),
            {"plan": result.plan},
        ),
        (
            "A2P_ARTIFACT_PROJECTION",
            _artifact_mutation(
                base,
                lambda d: d.__setitem__(
                    "projection_proof",
                    {
                        "source_node_count": len(result.plan.nodes) + 1,
                        "ir_node_count": len(result.plan.nodes) + 1,
                        "source_map_entry_count": len(result.plan.nodes) + 1,
                        "one_to_one": True,
                    },
                ),
            ),
            {"plan": result.plan},
        ),
        (
            "A2P_ARTIFACT_RELEASE",
            _artifact_mutation(
                base, lambda d: d["release_acceptance"].__setitem__("pinelib_rc6", "OTHER")
            ),
            {"target": target},
        ),
        (
            "A2P_ARTIFACT_IMPORT",
            _artifact_mutation(base, lambda d: d.__setitem__("import_manifest", ["__future__"])),
            {"emitted": result.emitted},
        ),
        (
            "A2P_ARTIFACT_ENTRYPOINT",
            _artifact_mutation(
                base, lambda d: d["entrypoint"].__setitem__("module", "other_module")
            ),
            {"emitted": result.emitted},
        ),
    ]
    for code, payload, kwargs in cases:
        _assert_code(
            code,
            lambda payload=payload, kwargs=kwargs: verify_generated_artifact_v3(payload, **kwargs),
        )
