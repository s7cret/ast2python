"""Malformed sealed target descriptions cannot bypass their structural admission."""

from copy import deepcopy

import pytest

from ast2python.errors import BundleInvariantError
from ast2python.lowering import TargetManifest, load_pinelib_target_manifest
from tests.test_target_qualifier_contracts import reseal


@pytest.fixture(scope="module")
def raw_target():
    return load_pinelib_target_manifest().to_dict()


def reject(raw, code):
    with pytest.raises(BundleInvariantError) as error:
        TargetManifest.from_mapping(reseal(raw))
    assert error.value.finding.code == code


@pytest.mark.parametrize(
    "field,code",
    [
        ("call_bindings", "A2P_TARGET_CALL_BINDINGS"),
        ("value_bindings", "A2P_TARGET_VALUE_BINDINGS"),
        ("capabilities", "A2P_TARGET_CAPABILITIES"),
        ("allowed_imports", "A2P_TARGET_IMPORTS"),
    ],
)
def test_target_collection_fields_are_arrays(raw_target, field, code):
    raw = deepcopy(raw_target)
    raw[field] = {}
    reject(raw, code)


def test_target_hash_type_is_not_coerced(raw_target):
    raw = deepcopy(raw_target)
    raw["content_hash"] = 1
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_HASH"):
        TargetManifest.from_mapping(raw)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("name", "", "A2P_TARGET_OPERATION_ID"),
        ("python_module", "os.path", "A2P_TARGET_OPERATION_MODULE"),
        ("parameter_bindings", {}, "A2P_TARGET_OPERATION_PARAMETERS"),
        ("parameter_bindings", [None], "A2P_TARGET_OPERATION_PARAMETERS"),
        (
            "parameter_bindings",
            [{"abi_parameter": "x", "binding": "UNKNOWN"}],
            "A2P_TARGET_OPERATION_PARAMETERS",
        ),
        (
            "parameter_bindings",
            [{"abi_parameter": "x", "binding": "OPERATION_ARGUMENT", "source_index": True}],
            "A2P_TARGET_OPERATION_PARAMETERS",
        ),
        (
            "parameter_bindings",
            [{"abi_parameter": "x", "binding": "OPERATION_ARGUMENT", "source_index": 1}],
            "A2P_TARGET_OPERATION_PARAMETERS",
        ),
    ],
)
def test_exact_primitive_metadata_is_structural_and_ordered(raw_target, field, value, code):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["operations"] if row.get("python_module") is not None)
    row[field] = value
    reject(raw, code)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("symbol_id", "", "A2P_TARGET_CALL_BINDING"),
        ("python_module", "os.path", "A2P_TARGET_PINELIB_MODULE"),
        ("parameter_bindings", {}, "A2P_TARGET_PARAMETER_BINDINGS"),
        ("parameter_bindings", [None], "A2P_TARGET_PARAMETER_BINDINGS"),
        (
            "parameter_bindings",
            [{"abi_parameter": "x", "binding": "INJECTED", "source": 1}],
            "A2P_TARGET_PARAMETER_BINDINGS",
        ),
    ],
)
def test_direct_call_metadata_never_infers_missing_abi(raw_target, field, value, code):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["call_bindings"] if row.get("python_module") is not None)
    row[field] = value
    reject(raw, code)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("delegation_owner", "", "A2P_TARGET_DELEGATED_CALL"),
        ("disposition", "unknown", "A2P_TARGET_CALL_BINDING"),
    ],
)
def test_delegated_call_identity_is_explicit(raw_target, field, value, code):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["call_bindings"] if row.get("disposition") == "TARGET_DELEGATED")
    row[field] = value
    reject(raw, code)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("symbol_id", "", "A2P_TARGET_VALUE_BINDING"),
        ("disposition", "unknown", "A2P_TARGET_VALUE_DISPOSITION"),
        ("python_module", "os.path", "A2P_TARGET_VALUE_CALLABLE"),
        ("parameter_bindings", {}, "A2P_TARGET_VALUE_PARAMETERS"),
        ("parameter_bindings", [None], "A2P_TARGET_VALUE_PARAMETERS"),
        (
            "parameter_bindings",
            [{"abi_parameter": "x", "binding": "INJECTED", "source": 1}],
            "A2P_TARGET_VALUE_PARAMETERS",
        ),
        ("return_type", "", "A2P_TARGET_VALUE_RETURN"),
        ("supported_pine_versions", [], "A2P_TARGET_VALUE_VERSIONS"),
        ("supported_pine_versions", [True], "A2P_TARGET_VALUE_VERSIONS"),
        ("supported_pine_versions", [7], "A2P_TARGET_VALUE_VERSIONS"),
        ("diagnostic", 1, "A2P_TARGET_VALUE_DIAGNOSTIC"),
    ],
)
def test_direct_value_metadata_requires_exact_types(raw_target, field, value, code):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["value_bindings"] if row.get("disposition") == "TARGET_DIRECT")
    row[field] = value
    reject(raw, code)


def test_value_field_inventory_cannot_grow_silently(raw_target):
    raw = deepcopy(raw_target)
    raw["value_bindings"][0]["unknown"] = True
    reject(raw, "A2P_TARGET_VALUE_BINDING")


def test_delegated_value_must_not_declare_a_direct_callable(raw_target):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["value_bindings"] if row.get("disposition") == "TARGET_DELEGATED")
    row["python_name"] = "read"
    reject(raw, "A2P_TARGET_VALUE_CALLABLE")


def test_delegated_value_requires_its_owner(raw_target):
    raw = deepcopy(raw_target)
    row = next(row for row in raw["value_bindings"] if row.get("disposition") == "TARGET_DELEGATED")
    row["delegation_owner"] = ""
    reject(raw, "A2P_TARGET_DELEGATED_VALUE")
