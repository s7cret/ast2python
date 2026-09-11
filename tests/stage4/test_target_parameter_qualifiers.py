"""Independent qualifier-order expectations and rehashed contract fault tests."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib.abi import load_target_manifest

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.lowering import load_pinelib_target_manifest, load_reference_target_manifest
from ast2python.lowering.qualifiers import audit_parameter_qualifiers
from ast2python.lowering.target import TargetManifest
from ast2python.lowering.validate import verify_lowering_plan_payload

QUALIFIERS = ("const", "input", "simple", "series")
# Manual expectation, not imported from the implementation.
ACCEPTED = {"const": {"const"}, "input": {"const", "input"},
            "simple": {"const", "input", "simple"}, "series": set(QUALIFIERS)}


def seal(body):
    result = copy.deepcopy(body)
    result.pop("content_hash", None)
    result["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    return result


def source(version=6, qualifier="series", *, named=False):
    declarations = {"const": "n=3", "input": "n=input.int(3)",
                    "simple": "simple int n=3", "series": "series int n=bar_index+1"}
    arguments = "length=n, source=close" if named else "close,n"
    return f'//@version={version}\nindicator("qualifiers")\n{declarations[qualifier]}\nx=ta.sma({arguments})\nplot(x)\n'


def narrow(tmp_path, ceiling, *, function="ta.sma", parameter="length"):
    raw = copy.deepcopy(load_target_manifest())
    row = next(row for row in raw["rows"] if row["name"] == function)
    next(p for p in row["parameters"] if p["name"] == parameter)["qualifier_max"] = ceiling
    path = tmp_path / "target.json"
    path.write_text(json.dumps(seal(raw)))
    return load_pinelib_target_manifest(path)


def compile_source(text, target):
    return compile_consumer_bundle(
        build_consumer_bundle(text, source_name="qualifiers.pine"),
        target=target, producer_commit="a" * 40,
    )


def binding(target, name="ta.sma"):
    return next(b for b in target.call_bindings.values()
                if b.symbol_id == "pine:function:" + name and b.call_form == "NAMESPACE_FUNCTION")


@pytest.mark.parametrize("version", (5, 6))
@pytest.mark.parametrize("actual", QUALIFIERS)
@pytest.mark.parametrize("ceiling", QUALIFIERS)
@pytest.mark.parametrize("named", (False, True))
def test_every_qualifier_pair_checked_at_target_boundary(tmp_path, version, actual, ceiling, named):
    target = narrow(tmp_path, ceiling)
    if actual in ACCEPTED[ceiling]:
        compile_source(source(version, actual, named=named), target)
    else:
        with pytest.raises(BundleInvariantError) as error:
            compile_source(source(version, actual, named=named), target)
        assert error.value.finding.code == "A2P_TARGET_ARGUMENT_QUALIFIER"
        assert error.value.finding.details["parameter"] == "length"
        assert error.value.finding.details["actual_qualifier"] == actual
        assert error.value.finding.details["target_qualifier_max"] == ceiling
        assert error.value.finding.details["source_span"]["start_line"] == 4


def test_contract_roundtrip_detached_immutable_and_hash_bound(tmp_path):
    target = load_pinelib_target_manifest()
    row = binding(target)
    assert row.parameter_qualifiers == {"source": "series", "length": "series"}
    assert TargetManifest.from_mapping(target.to_dict()).to_dict() == target.to_dict()
    detached = row.to_dict()
    detached["parameter_qualifiers"]["length"] = "const"
    assert row.parameter_qualifiers["length"] == "series"
    with pytest.raises(TypeError):
        row.parameter_qualifiers["length"] = "const"
    tightened = narrow(tmp_path, "simple")
    assert binding(tightened).parameter_qualifiers["length"] == "simple"
    assert tightened.content_hash != target.content_hash


@pytest.mark.parametrize("fault", ("removed", "null", "unknown", "extra", "missing", "bool", "list"))
def test_rehashed_normalized_target_cannot_drop_or_fake_ceilings(fault):
    body = load_pinelib_target_manifest().to_dict()
    row = next(r for r in body["call_bindings"] if r["symbol_id"] == "pine:function:ta.sma")
    if fault == "removed":
        row.pop("parameter_qualifiers")
    elif fault in {"null", "list"}:
        row["parameter_qualifiers"] = None if fault == "null" else []
    elif fault == "missing":
        row["parameter_qualifiers"].pop("length")
    elif fault == "extra":
        row["parameter_qualifiers"]["not_a_parameter"] = "series"
    else:
        row["parameter_qualifiers"]["length"] = True if fault == "bool" else "dynamic"
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_PARAMETER_QUALIFIERS"):
        TargetManifest.from_mapping(seal(body))


@pytest.mark.parametrize("fault", ("missing", "duplicate", "unknown", "bool"))
def test_rehashed_runtime_manifest_must_supply_explicit_ceilings(tmp_path, fault):
    raw = copy.deepcopy(load_target_manifest())
    row = next(r for r in raw["rows"] if r["name"] == "ta.sma")
    if fault == "missing":
        row["parameters"][0].pop("qualifier_max")
    elif fault == "duplicate":
        row["parameters"].append(copy.deepcopy(row["parameters"][0]))
    else:
        row["parameters"][0]["qualifier_max"] = False if fault == "bool" else "anything"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(seal(raw)))
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_PARAMETER_QUALIFIERS"):
        load_pinelib_target_manifest(path)


def test_reference_bindings_remain_explicitly_unverified():
    target = load_reference_target_manifest()
    assert TargetManifest.from_mapping(target.to_dict()).to_dict() == target.to_dict()
    row = next(iter(target.call_bindings.values()))
    assert audit_parameter_qualifiers(row, [], pine_version=row.supported_pine_versions[0]) == (
        "A2P_TARGET_PARAMETER_QUALIFIERS_UNVERIFIED",)


@pytest.mark.parametrize("ceiling", QUALIFIERS)
@pytest.mark.parametrize("source_ceiling", QUALIFIERS)
def test_signature_audit_does_not_certify_contract_from_one_safe_value(ceiling, source_ceiling):
    row = replace(binding(load_pinelib_target_manifest()),
                  parameter_qualifiers={"source": "series", "length": ceiling})
    findings = audit_parameter_qualifiers(row, [
        {"name": "source", "qualifier_max": "series"},
        {"name": "length", "qualifier_max": source_ceiling}], pine_version=6)
    assert findings == (() if source_ceiling in ACCEPTED[ceiling] else ("A2P_TARGET_QUALIFIER_CONTRACT",))


@pytest.mark.parametrize("version", (1, 2, 3, 4))
def test_historical_parameter_ceilings_are_not_overwritten_by_modern_rows(version):
    target = load_pinelib_target_manifest()
    # Existing historical producer policy is retained, not advertised as an external oracle.
    candidates = [row for row in target.call_bindings.values()
                  if row.symbol_id == "pine:function:ta.sma" and row.call_form == "FUNCTION"
                  and version in row.supported_pine_versions]
    assert candidates, "historical target coverage must not be vacuous"
    assert all(row.parameter_qualifiers["length"] == "series" for row in candidates)
    assert binding(target, "ta.ema").parameter_qualifiers["length"] == "simple"
    compile_source(f'//@version={version}\nstudy("historical")\nx=sma(close,close>0 ? 3 : 4)\nplot(x)\n', target)


@pytest.mark.parametrize("expression", ("math.max(1,close)", "math.max(close,1)", "math.max(1,2,close)"))
def test_each_variadic_operand_is_checked(tmp_path, expression):
    target = narrow(tmp_path, "simple", function="math.max", parameter="values")
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_ARGUMENT_QUALIFIER"):
        compile_source(f'//@version=6\nindicator("vararg")\nx={expression}\n', target)


@pytest.mark.parametrize("mutation", ("claim", "operand", "no_constraint", "name"))
def test_serialized_rehashed_plan_cannot_evade_operand_check(mutation):
    target = load_pinelib_target_manifest()
    result = compile_source(source(), target)
    payload = result.plan.to_dict()
    node = next(n for n in payload["nodes"] if n["attributes"].get("call", {}).get("symbol_id") == "pine:function:ta.sma")
    argument = node["attributes"]["call"]["arguments"][1]
    if mutation == "claim":
        argument["actual_qualifier"] = "const"
    elif mutation == "operand":
        arg_node = next(n for n in payload["nodes"] if n["source"]["node_id"] == argument["argument_node_id"])
        operand = next(n for n in payload["nodes"] if n["ir_id"] == arg_node["attributes"]["child_roles"]["value"][0])
        operand["result_type"]["qualifier"] = "const"
    elif mutation == "name":
        argument["parameter_name"] = "invented"
    else:
        rows = dict(target.call_bindings)
        row = binding(target)
        rows[row.key] = replace(row, parameter_qualifiers=None)
        target = replace(target, call_bindings=rows)
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_(ARGUMENT_QUALIFIER|PARAMETER_QUALIFIERS)"):
        verify_lowering_plan_payload(seal(payload), target=target)


@pytest.mark.parametrize("version", (1, 2, 3, 4))
def test_legacy_request_qualifier_uses_only_declared_timeframe_injection(version):
    from ast2python.lowering.qualifiers import audit_parameter_qualifiers
    target = load_pinelib_target_manifest()
    row = next(b for b in target.call_bindings.values()
               if b.symbol_id == "pine:function:request.security" and b.call_form == "FUNCTION")
    assert audit_parameter_qualifiers(row, [{"name": "resolution", "qualifier_max": "simple"}],
                                     pine_version=version) == ()
    unmapped = replace(row, parameter_bindings=())
    assert audit_parameter_qualifiers(unmapped, [{"name": "resolution", "qualifier_max": "simple"}],
                                     pine_version=version) == ("A2P_TARGET_PARAMETER_QUALIFIER_MISSING",)
    compile_source(f'//@version={version}\nstudy("request")\nx=security("X","1D",close)\nplot(x)\n',target)


@pytest.mark.parametrize("kind,scope", [("input.int", "admitted_input_metadata"),
    ("strategy.risk.max_position_size", "host_delegation"), ("ta.sma", "direct_runtime")])
def test_admission_owners_are_explicit_and_all_ceilings_retained(kind, scope):
    from ast2python.lowering.qualifiers import qualifier_scope
    target = load_pinelib_target_manifest()
    row = binding(target, kind)
    assert qualifier_scope(row) == scope
    assert set(row.parameter_qualifiers) == set(row.parameters)


@pytest.mark.parametrize("field", ("parameter_name", "argument_node_id"))
def test_rehashed_plan_invalid_argument_id_has_structured_rejection(field):
    target = load_pinelib_target_manifest()
    payload = compile_source(source(), target).plan.to_dict()
    node = next(n for n in payload["nodes"] if n["attributes"].get("call", {}).get("symbol_id") == "pine:function:ta.sma")
    node["attributes"]["call"]["arguments"][0][field] = []
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_ARGUMENT_QUALIFIER"):
        verify_lowering_plan_payload(seal(payload), target=target)
