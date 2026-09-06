"""Exact manifests may not inherit missing executable reference primitives."""
import hashlib
import json
from importlib.resources import files

import pytest
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest


def write_target(tmp_path, mutate):
    raw = json.loads(files("pinelib.abi").joinpath("target_manifest.json").read_text())
    mutate(raw)
    raw["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(
        {key: value for key, value in raw.items() if key != "content_hash"})).hexdigest()
    path = tmp_path / "target.json"
    path.write_text(json.dumps(raw))
    return path


@pytest.mark.parametrize("opcode", ["operator.binary", "operator.unary", "series.history"])
def test_missing_runtime_primitive_fails_even_with_valid_hash(tmp_path, opcode):
    def remove(raw):
        raw["compiler_operations"] = [r for r in raw["compiler_operations"] if r["name"] != opcode]
    with pytest.raises(BundleInvariantError) as error:
        load_pinelib_target_manifest(write_target(tmp_path, remove))
    assert error.value.finding.code == "A2P_PINELIB_REQUIRED_OPERATION"
    assert error.value.finding.details["missing"] == [opcode]


def test_duplicate_runtime_primitive_rejected(tmp_path):
    with pytest.raises(BundleInvariantError, match="duplicate"):
        load_pinelib_target_manifest(write_target(tmp_path,
            lambda raw: raw["compiler_operations"].append(raw["compiler_operations"][0])))


def test_structural_lowering_stays_compiler_owned():
    target = load_pinelib_target_manifest()
    assert target.release_acceptance == "EXACT_PINELIB_TARGET_MANIFEST_V2"
    for opcode in ("operator.binary", "operator.unary", "series.history"):
        assert target.operations[opcode].python_module.startswith("pinelib.")
    assert "control.if" in target.operations
