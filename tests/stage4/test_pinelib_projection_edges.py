"""Admission of exact PineLib metadata uses seals, identities and declared ABI."""

import json
from copy import deepcopy

import pytest
from pinelib.abi import load_target_manifest

from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_target_qualifier_contracts import reseal


@pytest.fixture(scope="module")
def source():
    return load_target_manifest()


def reject_source(tmp_path, raw, code, *, rehash=True):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(reseal(raw) if rehash else raw), encoding="utf-8")
    with pytest.raises(BundleInvariantError) as error:
        load_pinelib_target_manifest(path)
    assert error.value.finding.code == code


@pytest.mark.parametrize("raw", [[], {}])
def test_source_schema_is_exact(tmp_path, raw):
    reject_source(tmp_path, raw, "A2P_PINELIB_TARGET_SCHEMA", rehash=False)


def test_source_hash_is_verified_before_projection(source, tmp_path):
    raw = deepcopy(source)
    raw["content_hash"] = "sha256:" + "1" * 64
    reject_source(tmp_path, raw, "A2P_PINELIB_TARGET_HASH", rehash=False)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("compiler_operations", None, "A2P_PINELIB_COMPILER_OPERATIONS"),
        ("compiler_operations", [None], "A2P_PINELIB_COMPILER_OPERATION"),
        ("rows", {}, "A2P_PINELIB_TARGET_ROWS"),
    ],
)
def test_source_arrays_are_not_reconstructed(source, tmp_path, field, value, code):
    raw = deepcopy(source)
    raw[field] = value
    reject_source(tmp_path, raw, code)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("abi_callable", None, "A2P_PINELIB_COMPILER_OPERATION"),
        ("abi_callable", "os.path", "A2P_PINELIB_COMPILER_OPERATION"),
        ("evaluation", "unknown", "A2P_PINELIB_COMPILER_OPERATION_POLICY"),
        ("parameter_bindings", {}, "A2P_PINELIB_COMPILER_OPERATION"),
    ],
)
def test_operation_requires_declared_lowering_policy_and_callable(
    source, tmp_path, field, value, code
):
    raw = deepcopy(source)
    raw["compiler_operations"][0][field] = value
    reject_source(tmp_path, raw, code)


@pytest.mark.parametrize(
    "category,field,value,code",
    [
        ("call", "abi_callable", None, "A2P_PINELIB_TARGET_CALLABLE"),
        ("call", "version_availability", [], "A2P_PINELIB_TARGET_VERSIONS"),
        ("call", "parameter_bindings", None, "A2P_PINELIB_TARGET_PARAMETERS"),
        ("value", "disposition", "UNKNOWN", "A2P_PINELIB_VALUE_DISPOSITION"),
        ("value", "parameter_bindings", None, "A2P_PINELIB_TARGET_PARAMETERS"),
        ("value", "version_availability", [], "A2P_PINELIB_TARGET_VERSIONS"),
    ],
)
def test_direct_rows_have_explicit_versions_parameters_and_dispositions(
    source, tmp_path, category, field, value, code
):
    raw = deepcopy(source)
    is_value = category == "value"
    row = next(
        row
        for row in raw["rows"]
        if row["disposition"] == "TARGET_DIRECT"
        and (row["category"] in {"variables", "constants"}) == is_value
    )
    row[field] = value
    reject_source(tmp_path, raw, code)


@pytest.mark.parametrize("delegation", [{}, {"owner": "", "schema_id": "s", "capability_id": "c"}])
def test_delegated_source_rows_have_complete_host_identity(source, tmp_path, delegation):
    raw = deepcopy(source)
    row = next(row for row in raw["rows"] if row["disposition"] == "TARGET_DELEGATED")
    row["delegation"] = delegation
    reject_source(tmp_path, raw, "A2P_PINELIB_TARGET_DELEGATION")


def test_conflicting_value_rows_do_not_overwrite_the_first_projection(source, tmp_path):
    raw = deepcopy(source)
    row = next(
        row
        for row in raw["rows"]
        if row["category"] in {"variables", "constants"} and row["disposition"] == "TARGET_DIRECT"
    )
    duplicate = deepcopy(row)
    duplicate["return"]["runtime_type"] = "conflicting_type"
    raw["rows"].append(duplicate)
    reject_source(tmp_path, raw, "A2P_PINELIB_VALUE_DUPLICATE")
