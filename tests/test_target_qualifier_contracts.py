"""Independent qualifier lattice and exact-target roundtrip/admission regressions.

The 4-element order is the documented Pine type system; no expected values are
copied from compiler execution. These tests do not certify the full Pine catalog.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib.abi import load_target_manifest

from ast2python import compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes, freeze_json, thaw_json
from ast2python.emission import emit_python_module
from ast2python.errors import BundleInvariantError
from ast2python.lowering import (
    TargetManifest,
    audit_pinelib_qualifier_binding,
    load_pinelib_target_manifest,
    load_reference_target_manifest,
)
from ast2python.lowering.qualifiers import validate_call_qualifiers

QUALIFIERS = ("const", "input", "simple", "series")


@pytest.fixture(scope="module")
def target():
    return load_pinelib_target_manifest()


def row(target, symbol="ta.sma", form="NAMESPACE_FUNCTION"):
    symbol = "pine:function:" + symbol
    return target.call_bindings[(symbol, symbol + "#canonical", form)]


def reseal(raw):
    raw["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes({k: v for k, v in raw.items() if k != "content_hash"})
        ).hexdigest()
    )
    return raw


def changed_target(target, symbol, name, qualifier, *, form="NAMESPACE_FUNCTION"):
    raw = target.to_dict()
    binding = next(
        b
        for b in raw["call_bindings"]
        if b["symbol_id"] == "pine:function:" + symbol and b["call_form"] == form
    )
    binding["parameter_qualifiers"][name] = qualifier
    return TargetManifest.from_mapping(reseal(raw))


def compile_body(body, target, version=6):
    source = (
        f'//@version={version}\n{"indicator" if version >= 5 else "study"}("qualifiers")\n{body}\n'
    )
    # The compiler gets a source-free bundle: it must not rely on re-reading text.
    bundle = build_consumer_bundle(source, producer_commit="1" * 40)
    assert set(bundle["source"]) == {"name", "encoding", "byte_length", "source_hash"}
    return compile_consumer_bundle(
        bundle, target=target, producer_commit="2" * 40, expected_pine2ast_commit="1" * 40
    )


def test_exact_normalization_retains_all_declared_qualifiers(target):
    raw = load_target_manifest()
    assert target.schema_id == "ast2python.target_manifest.v2"
    assert target.schema_version == "2.0.0"
    assert all(b.parameter_qualifiers is not None for b in target.call_bindings.values())
    originals = raw["rows"] + raw.get("historical_call_bindings", [])
    supported = [
        r
        for r in originals
        if r.get("category") not in {"constants", "variables"}
        and r["disposition"] in {"TARGET_DIRECT", "TARGET_DELEGATED"}
    ]
    # Every projected binding is backed by the exact raw qualifier map, not a
    # global const/series default and not a source-catalogue reconstruction.
    for binding in target.call_bindings.values():
        candidates = [
            r
            for r in supported
            if binding.symbol_id in set(r.get("source_symbol_ids", [])) | {r["symbol_id"]}
            and set(binding.supported_pine_versions) == set(r["version_availability"])
            and binding.parameters == tuple(p["name"] for p in r["parameters"])
        ]
        assert candidates, binding.key
        assert any(
            dict(binding.parameter_qualifiers)
            == {p["name"]: p["qualifier_max"] for p in r["parameters"]}
            for r in candidates
        ), binding.key


def test_roundtrip_hash_and_detached_read_only_maps(target):
    assert TargetManifest.from_mapping(target.to_dict()).to_dict() == target.to_dict()
    binding = row(target, "ta.ema")
    assert binding.parameter_qualifiers["length"] == "simple"
    with pytest.raises(TypeError):
        binding.parameter_qualifiers["length"] = "series"
    raw = target.to_dict()
    original = TargetManifest.from_mapping(raw)
    for b in raw["call_bindings"]:
        b["parameter_qualifiers"].clear()
    assert original.to_dict() == target.to_dict()
    modified = changed_target(target, "ta.ema", "length", "series")
    assert modified.content_hash != target.content_hash


@pytest.mark.parametrize(
    "fault", ["absent", "empty", "extra", "list", "null", "bool", "number", "unknown"]
)
def test_rehashed_normalized_contract_must_be_complete_and_typed(target, fault):
    raw = target.to_dict()
    b = next(b for b in raw["call_bindings"] if b["symbol_id"] == "pine:function:ta.ema")
    if fault == "absent":
        b.pop("parameter_qualifiers")
    elif fault == "empty":
        b["parameter_qualifiers"] = {}
    elif fault == "extra":
        b["parameter_qualifiers"]["invented"] = "series"
    elif fault in {"list", "null"}:
        b["parameter_qualifiers"] = [] if fault == "list" else None
    else:
        b["parameter_qualifiers"]["length"] = {"bool": True, "number": 1, "unknown": "SERIES"}[
            fault
        ]
    with pytest.raises(BundleInvariantError):
        TargetManifest.from_mapping(reseal(raw))


@pytest.mark.parametrize(
    "fault", ["absent", "null", "list", "empty_name", "duplicate", "unknown", "non_object"]
)
def test_rehashed_raw_manifest_cannot_drop_or_invent_qualifiers(tmp_path, fault):
    raw = deepcopy(load_target_manifest())
    b = next(r for r in raw["rows"] if r["symbol_id"] == "pine:function:ta.ema")
    if fault == "absent":
        b["parameters"][1].pop("qualifier_max")
    elif fault in {"null", "list", "unknown"}:
        b["parameters"][1]["qualifier_max"] = {
            "null": None,
            "list": ["simple"],
            "unknown": "dynamic",
        }[fault]
    elif fault == "empty_name":
        b["parameters"][1]["name"] = ""
    elif fault == "duplicate":
        b["parameters"].append(deepcopy(b["parameters"][1]))
    else:
        b["parameters"][1] = "length"
    path = tmp_path / "target.json"
    path.write_text(json.dumps(reseal(raw)))
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_TARGET_QUALIFIERS"):
        load_pinelib_target_manifest(path)


def test_old_reference_format_is_preserved_but_cannot_impersonate_exact(target):
    reference = load_reference_target_manifest()
    assert reference.schema_id == "ast2python.target_manifest.v1"
    assert TargetManifest.from_mapping(reference.to_dict()).to_dict() == reference.to_dict()
    old = target.to_dict()
    old.update(schema_id="ast2python.target_manifest.v1", schema_version="1.0.0")
    for b in old["call_bindings"]:
        b.pop("parameter_qualifiers")
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_QUALIFIER_SCHEMA"):
        TargetManifest.from_mapping(reseal(old))


@pytest.mark.parametrize("source_max", QUALIFIERS)
@pytest.mark.parametrize("target_max", QUALIFIERS)
def test_signature_domain_inclusion_is_directional(target, source_max, target_max):
    binding = replace(row(target), parameter_qualifiers={"source": "series", "length": target_max})
    findings = audit_pinelib_qualifier_binding(
        binding,
        [
            {"name": "source", "qualifier_max": "series"},
            {"name": "length", "qualifier_max": source_max},
        ],
        pine_version=6,
    )
    assert bool(findings) == (QUALIFIERS.index(source_max) > QUALIFIERS.index(target_max))
    if findings:
        assert findings == ("A2P_TARGET_QUALIFIER_CONTRACT",)


@pytest.mark.parametrize("actual", QUALIFIERS)
@pytest.mark.parametrize("source_max", QUALIFIERS)
@pytest.mark.parametrize("target_max", QUALIFIERS)
def test_actual_qualifier_must_fit_both_contracts(target, actual, source_max, target_max):
    binding = replace(row(target), parameter_qualifiers={"source": "series", "length": target_max})
    call = {
        "arguments": [
            {"parameter_name": "length", "actual_qualifier": actual, "max_qualifier": source_max}
        ]
    }
    valid = QUALIFIERS.index(actual) <= min(
        QUALIFIERS.index(source_max), QUALIFIERS.index(target_max)
    )
    if valid:
        validate_call_qualifiers(call, binding, node_id="n:test", pine_version=6)
    else:
        with pytest.raises(BundleInvariantError) as error:
            validate_call_qualifiers(call, binding, node_id="n:test", pine_version=6)
        assert error.value.finding.details["actual_qualifier"] == actual
        assert error.value.finding.details["parameter"] == "length"


@pytest.mark.parametrize(
    "body", ["x=ta.sma(close,bar_index+1)", "x=ta.sma(length=bar_index+1,source=close)"]
)
def test_source_free_admitted_series_call_rejected_by_narrower_target(target, body):
    narrow = changed_target(target, "ta.sma", "length", "simple")
    assert compile_body(body, target).emitted.code
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_ARGUMENT_QUALIFIER"):
        compile_body(body, narrow)


@pytest.mark.parametrize("version", range(1, 7))
def test_constant_remains_legal_without_claiming_full_signature_compatibility(target, version):
    fn = "ta.sma" if version >= 5 else "sma"
    form = "NAMESPACE_FUNCTION" if version >= 5 else "FUNCTION"
    narrow = changed_target(target, "ta.sma", "length", "simple", form=form)
    assert compile_body(f"x={fn}(close,3)", narrow, version).emitted.code
    assert audit_pinelib_qualifier_binding(
        row(narrow, "ta.sma", form),
        [{"name": "length", "qualifier_max": "series"}],
        pine_version=version,
    ) == ("A2P_TARGET_QUALIFIER_CONTRACT",)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "prefix,argument", [("", "3"), ("n=input.int(3)\n", "n"), ("simple int n=3\n", "n")]
)
def test_recursive_builtin_accepts_all_weaker_qualifiers(target, version, prefix, argument):
    assert compile_body(prefix + f"x=ta.ema(close,{argument})", target, version).emitted.code


def test_emission_rechecks_target_after_lowering(target):
    result = compile_body("x=ta.sma(close,bar_index+1)", target)
    narrow = changed_target(target, "ta.sma", "length", "simple")
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_ARGUMENT_QUALIFIER"):
        emit_python_module(result.plan, narrow)


def test_rehashed_plan_cannot_weaken_actual_or_producer_ceilings(target):
    result = compile_body("x=ta.ema(close,3)", target)
    call_node = next(
        n
        for n in result.plan.nodes.values()
        if n.attributes.get("call", {}).get("symbol_id") == "pine:function:ta.ema"
    )
    attrs = thaw_json(call_node.attributes)
    attrs["call"]["arguments"][1]["actual_qualifier"] = "series"
    forged_node = replace(call_node, attributes=freeze_json(attrs))
    plan = replace(result.plan, nodes={**result.plan.nodes, call_node.ir_id: forged_node})
    plan = replace(plan, content_hash=reseal(plan.to_dict())["content_hash"])
    # Emitter has a separate check even outside compile_consumer_bundle.
    with pytest.raises(BundleInvariantError, match="A2P_CALL_QUALIFIER"):
        emit_python_module(plan, target)


@pytest.mark.parametrize("form", ["FUNCTION", "NAMESPACE_FUNCTION"])
def test_variadic_all_operands_checked_not_just_first(target, form):
    b = row(target, "math.max", form)
    b = replace(b, parameter_qualifiers={"values": "simple"})
    call = {
        "arguments": [
            {"parameter_name": "values", "actual_qualifier": q, "max_qualifier": "series"}
            for q in ("const", "input", "series")
        ]
    }
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_ARGUMENT_QUALIFIER"):
        validate_call_qualifiers(call, b, node_id="n:test", pine_version=6)


@pytest.mark.parametrize("version", range(1, 7))
def test_legacy_request_role_is_version_bounded_and_not_a_global_alias(target, version):
    b = row(target, "request.security", "FUNCTION" if version < 5 else "NAMESPACE_FUNCTION")
    call = {
        "arguments": [
            {"parameter_name": "resolution", "actual_qualifier": "const", "max_qualifier": "series"}
        ]
    }
    if version < 5:
        validate_call_qualifiers(call, b, node_id="n:test", pine_version=version)
    else:
        with pytest.raises(BundleInvariantError, match="A2P_TARGET_QUALIFIER_PARAMETER"):
            validate_call_qualifiers(call, b, node_id="n:test", pine_version=version)
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_QUALIFIER_PARAMETER"):
        validate_call_qualifiers(call, row(target), node_id="n:test", pine_version=version)


@pytest.mark.parametrize(
    "parameters", [None, {}, [], [{"name": "length"}], [{"name": "length", "qualifier_max": False}]]
)
def test_incomplete_source_metadata_is_never_reported_compatible(target, parameters):
    assert "A2P_SOURCE_QUALIFIERS_UNVERIFIED" in audit_pinelib_qualifier_binding(
        row(target), parameters, pine_version=6
    )


@pytest.mark.parametrize("version", [4, 5, 6])
def test_admitted_input_emission_cannot_bypass_qualifier_check(target, version):
    name = "input.int" if version >= 5 else "input"
    result = compile_body(f"n={name}(3)\nx=close+n", target, version)
    node = next(
        n for n in result.plan.nodes.values() if n.attributes.get("call", {}).get("callee") == name
    )
    attrs = thaw_json(node.attributes)
    argument = next(a for a in attrs["call"]["arguments"] if a["parameter_name"] == "defval")
    argument["actual_qualifier"] = "series"
    corrupted = replace(node, attributes=freeze_json(attrs))
    plan = replace(result.plan, nodes={**result.plan.nodes, node.ir_id: corrupted})
    plan = replace(plan, content_hash=reseal(plan.to_dict())["content_hash"])
    with pytest.raises(BundleInvariantError, match="A2P_CALL_QUALIFIER"):
        emit_python_module(plan, target)
