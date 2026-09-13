"""Exact-target reservation is declared, never inferred from a runtime method."""

import json
from copy import deepcopy

import pytest
from pinelib.abi import load_target_manifest

from ast2python import load_pinelib_target_manifest
from ast2python.errors import BundleInvariantError
from tests.test_target_qualifier_contracts import reseal

CONTRACT = {
    "revision": 1,
    "operation": "state.reserve_history.v1",
    "capability": "compiler.history_reservation.v1",
    "supported_pine_versions": [1, 2],
    "scalar_types": ["bool", "color", "float", "int", "string"],
    "history_policies": ["each_bar"],
    "reservation": "typed-storage-without-evaluation",
    "rollback": "transactional",
}
BINDINGS = [
    {"abi_parameter": "tx", "binding": "INJECTED", "source": "RUNTIME_TRANSACTION"},
    {"abi_parameter": "series_id", "binding": "OPERATION_ARGUMENT", "source_index": 0},
    {"abi_parameter": "dtype", "binding": "OPERATION_ARGUMENT", "source_index": 1},
    {"abi_parameter": "history_policy", "binding": "OPERATION_ARGUMENT", "source_index": 2},
]


def target_source():
    # Synthetic declared-ABI fixture; native implementation is tested in PineLib.
    raw = deepcopy(load_target_manifest())
    raw["compiled_history_reservation"] = deepcopy(CONTRACT)
    raw["compiler_operations"] = [
        row for row in raw["compiler_operations"] if row["name"] != CONTRACT["operation"]
    ]
    raw["compiler_operations"].append(
        {
            "name": CONTRACT["operation"],
            "evaluation": "eager",
            "effect": "state",
            "abi_callable": "pinelib.abi.primitives.reserve_history_v1",
            "parameter_bindings": deepcopy(BINDINGS),
        }
    )
    return raw


def admit(tmp_path, raw):
    path = tmp_path / "target.json"
    path.write_text(json.dumps(reseal(raw)), encoding="utf-8")
    return load_pinelib_target_manifest(path)


def test_reservation_contract_admits_exact_versioned_primitive(tmp_path):
    target = admit(tmp_path, target_source())
    assert "compiler.history_reservation.v1" in target.capabilities
    operation = target.operations["state.reserve_history.v1"]
    assert operation.python_module == "pinelib.abi.primitives"
    assert operation.python_name == "reserve_history_v1"
    assert operation.evaluation == "eager"
    assert operation.effect == "state"


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 1.0),
        ("revision", 2),
        ("supported_pine_versions", [True, 2]),
        ("supported_pine_versions", [1, 2, 3]),
        ("reservation", "write-default-value"),
        ("rollback", "none"),
        ("history_policies", ["each_bar", "on_evaluation"]),
    ],
)
def test_reservation_descriptor_is_exact_and_type_preserving(tmp_path, field, value):
    raw = target_source()
    raw["compiled_history_reservation"][field] = value
    with pytest.raises(BundleInvariantError, match="A2P_HISTORY_RESERVATION_CONTRACT"):
        admit(tmp_path, raw)


def test_reservation_capability_requires_a_declared_operation(tmp_path):
    raw = target_source()
    raw["compiler_operations"].pop()
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_REQUIRED_OPERATION"):
        admit(tmp_path, raw)


@pytest.mark.parametrize("mutation", ["callable", "binding", "bool_index", "descriptor"])
def test_reservation_operation_cannot_supply_a_different_abi(tmp_path, mutation):
    raw = target_source()
    if mutation == "callable":
        raw["compiler_operations"][-1]["abi_callable"] = "pinelib.abi.primitives.series_history_v1"
    elif mutation == "binding":
        raw["compiler_operations"][-1]["parameter_bindings"][-1]["source_index"] = 1
    elif mutation == "bool_index":
        raw["compiler_operations"][-1]["parameter_bindings"][1]["source_index"] = False
    else:
        del raw["compiled_history_reservation"]
    with pytest.raises(BundleInvariantError, match="A2P_HISTORY_RESERVATION_CONTRACT"):
        admit(tmp_path, raw)
