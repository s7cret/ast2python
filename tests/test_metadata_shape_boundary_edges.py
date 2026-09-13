"""Independent artifact identity, type-shape and qualifier boundary regressions."""

import importlib
from copy import deepcopy
from dataclasses import replace

import pytest

from ast2python.artifacts.script_metadata import admitted_script_metadata
from ast2python.emission.loop_types import missing_value_expression
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest
from ast2python.lowering.qualifiers import (
    audit_pinelib_qualifier_binding,
    project_parameter_qualifiers,
    validate_call_qualifiers,
)


def metadata(version=6):
    return {
        "schema_id": "ast2python.script_metadata.v1",
        "pine_version": version,
        "source_hash": "sha256:" + "a" * 64,
        "declaration": {"title": "example"},
        "inputs": {"input:1": {"kind": "int", "defval": 1}},
    }


def envelope(version=6):
    return {"version_context": {"pine_version": version}, "source_hash": "sha256:" + "a" * 64}


@pytest.mark.parametrize("version", range(1, 7))
def test_admitted_metadata_is_detached_and_version_bound(version):
    source = metadata(version)
    admitted = admitted_script_metadata({"SCRIPT_METADATA": source}, envelope(version))
    assert admitted == source
    admitted["inputs"]["input:1"]["defval"] = 99
    assert source["inputs"]["input:1"]["defval"] == 1


def test_legacy_absence_does_not_infer_inputs_from_titles():
    assert admitted_script_metadata({"title": "input.int(10)"}, envelope()) == {
        "inputs": {},
        "declaration": {},
    }


@pytest.mark.parametrize("bad", [1, [], {}, {"schema_id": "ast2python.script_metadata.v1"}])
def test_metadata_requires_its_exact_object_envelope(bad):
    with pytest.raises(ValueError, match="malformed"):
        admitted_script_metadata({"SCRIPT_METADATA": bad}, envelope())


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_id", "other"),
        ("pine_version", 5),
        ("source_hash", "sha256:" + "b" * 64),
        ("inputs", []),
        ("declaration", "title"),
    ],
)
def test_metadata_does_not_accept_changed_identity_or_descriptor_shape(field, value):
    bad = deepcopy(metadata())
    bad[field] = value
    with pytest.raises(ValueError):
        admitted_script_metadata({"SCRIPT_METADATA": bad}, envelope())


@pytest.mark.parametrize("version", [True, 1.0])
def test_metadata_pine_version_is_not_python_numeric_equality(version):
    with pytest.raises(ValueError, match="identity"):
        admitted_script_metadata({"SCRIPT_METADATA": metadata(version)}, envelope(1))


@pytest.mark.parametrize(
    "dtype", ["tuple<int", "tuple<int>>", "tuple<>", "tuple<int,>", "tuple<array<int>"]
)
def test_malformed_tuple_return_types_are_not_guessed(dtype):
    with pytest.raises(BundleInvariantError) as error:
        missing_value_expression(dtype, 6)
    assert error.value.finding.code == "A2P_LOOP_RETURN_TYPE"


def test_nested_missing_tuple_values_preserve_version_and_shape():
    assert (
        missing_value_expression("tuple<bool,tuple<int,bool>>", 6)
        == "(False, (_PineLibNA, False,),)"
    )
    assert (
        missing_value_expression("tuple<bool,tuple<int,bool>>", 5)
        == "(_PineLibNA, (_PineLibNA, _PineLibNA,),)"
    )


def test_mixin_host_protocol_has_no_runtime_implementation_or_import_cycle():
    module = importlib.import_module("ast2python.emission.context")
    assert not hasattr(module, "EmissionContext")


@pytest.fixture(scope="module")
def binding():
    target = load_pinelib_target_manifest()
    return target.call_bindings[
        ("pine:function:ta.sma", "pine:function:ta.sma#canonical", "NAMESPACE_FUNCTION")
    ]


@pytest.mark.parametrize("rows", [None, {}, "parameters"])
def test_runtime_parameter_rows_must_be_explicit_array(rows):
    with pytest.raises(BundleInvariantError) as error:
        project_parameter_qualifiers(rows, symbol_id="pine:function:ta.sma")
    assert error.value.finding.code == "A2P_PINELIB_TARGET_QUALIFIERS"


def test_qualifier_audit_keeps_bad_version_and_bad_target_as_independent_reasons(binding):
    corrupted = replace(binding, parameter_qualifiers={})
    reasons = audit_pinelib_qualifier_binding(corrupted, [], pine_version=99)
    assert set(reasons) == {"A2P_TARGET_CALL_BINDING", "A2P_TARGET_PARAMETER_QUALIFIERS"}


def test_qualifier_audit_does_not_guess_missing_target_parameter(binding):
    reasons = audit_pinelib_qualifier_binding(
        binding, [{"name": "unknown", "qualifier_max": "const"}], pine_version=6
    )
    assert "A2P_TARGET_QUALIFIER_PARAMETER" in reasons


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        {},
        [1],
        [{}],
        [{"parameter_name": ""}],
        [{"parameter_name": "source", "max_qualifier": "bogus", "actual_qualifier": "const"}],
        [{"parameter_name": "source", "max_qualifier": "series", "actual_qualifier": True}],
    ],
)
def test_call_qualifier_evidence_is_structural_and_exact(binding, arguments):
    with pytest.raises(BundleInvariantError) as error:
        validate_call_qualifiers(
            {"arguments": arguments}, binding, node_id="node:1", pine_version=6
        )
    assert error.value.finding.code == "A2P_CALL_QUALIFIER"
