from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from pine2ast.hardening.consumer_bundle import build_consumer_bundle

from ast2python import compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest

PINELIB_MANIFEST = Path(str(files("pinelib.abi").joinpath("target_manifest.json")))


def target():
    return load_pinelib_target_manifest(PINELIB_MANIFEST)


def test_exact_target_binds_bool_and_int_casts() -> None:
    raw = json.loads(PINELIB_MANIFEST.read_text())
    for name in ("bool", "int"):
        rows = [
            row
            for row in raw["rows"]
            if row["name"] == name and row["disposition"] == "TARGET_DIRECT"
        ]
        assert rows
        assert all(
            binding["binding"] != "UNBOUND_FAIL_CLOSED"
            for row in rows
            for binding in row["parameter_bindings"]
        )


def test_generated_bool_int_and_dynamic_history_use_exact_runtime_contracts() -> None:
    source = """//@version=6
indicator("stage22")
int n = bar_index % 3
b = bool(n)
i = int(close)
x = close[n]
plot(b ? i : x)
"""
    result = compile_consumer_bundle(
        build_consumer_bundle(source, source_name="stage22.pine"),
        target=target(),
        module_name="stage22_generated",
    )
    code = result.emitted.code
    assert "from pinelib.abi.primitives import bool_v1" in code
    assert "from pinelib.abi.primitives import int_v1" in code
    assert "series_history_v1" in code or "history_value_v1" in code
    assert "bool(n)" not in code


def test_v5_and_v6_generated_condition_paths_remain_version_exact() -> None:
    v5 = """//@version=5
indicator("v5")
plot(bar_index ? 1 : 0)
"""
    result5 = compile_consumer_bundle(
        build_consumer_bundle(v5, source_name="v5.pine"),
        target=target(),
        module_name="stage22_v5",
    )
    assert "condition_v1" in result5.emitted.code

    v6 = """//@version=6
indicator("v6")
plot(bool(bar_index) ? 1 : 0)
"""
    result6 = compile_consumer_bundle(
        build_consumer_bundle(v6, source_name="v6.pine"),
        target=target(),
        module_name="stage22_v6",
    )
    assert "bool_v1" in result6.emitted.code
    assert "condition_v1" in result6.emitted.code
