"""Historical bindings are explicit producer identities, never spelling guesses."""

import hashlib
import json
from copy import deepcopy

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib.abi import load_target_manifest

from ast2python import compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest


def load_mutated(tmp_path, mutate):
    manifest = deepcopy(load_target_manifest())
    mutate(manifest)
    body = {key: value for key, value in manifest.items() if key != "content_hash"}
    manifest["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    path = tmp_path / "target.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_pinelib_target_manifest(path)


def exp_row(manifest, historical=False):
    rows = manifest["historical_call_bindings" if historical else "rows"]
    return next(row for row in rows if row["name"] == ("exp" if historical else "math.exp"))


def test_canonical_symbols_keep_distinct_source_parameters_and_call_forms():
    target = load_pinelib_target_manifest()
    symbol = "pine:function:math.exp"
    modern = target.call_bindings[(symbol, symbol + "#canonical", "NAMESPACE_FUNCTION")]
    historical = target.call_bindings[(symbol, symbol + "#canonical", "FUNCTION")]
    assert modern.supported_pine_versions == (5, 6)
    assert historical.supported_pine_versions == (1, 2, 3, 4)
    assert modern.parameters == ("number",)
    assert historical.parameters == ("x",)
    assert modern.parameter_bindings == (
        {"abi_parameter": "value", "binding": "SOURCE_PARAMETER", "source": "number"},
    )
    assert historical.parameter_bindings == (
        {"abi_parameter": "value", "binding": "SOURCE_PARAMETER", "source": "x"},
    )
    # A textual legacy alias in source_symbol_ids does not authorize inventing
    # an overload absent from the producer's explicit identity table.
    assert (
        "pine:function:exp",
        "pine:function:exp#canonical",
        "FUNCTION",
    ) not in target.call_bindings


def test_missing_historical_table_is_not_synthesized_from_modern_rows(tmp_path):
    target = load_mutated(tmp_path, lambda manifest: manifest.pop("historical_call_bindings"))
    with pytest.raises(BundleInvariantError, match="A2P_TARGET_CALL_BINDING"):
        compile_consumer_bundle(
            build_consumer_bundle('//@version=4\nstudy("x")\nplot(exp(1))\n'), target=target
        )
    compile_consumer_bundle(
        build_consumer_bundle('//@version=6\nindicator("x")\nplot(math.exp(1))\n'), target=target
    )


@pytest.mark.parametrize("value", [None, {}, "FUNCTION"])
def test_malformed_historical_table_fails_closed(tmp_path, value):
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_HISTORICAL_BINDINGS"):
        load_mutated(tmp_path, lambda manifest: manifest.update(historical_call_bindings=value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("producer_call_forms", ["NAMESPACE_FUNCTION"]),
        ("producer_overload_ids", []),
        ("producer_overload_ids", ["pine:function:unrelated#canonical"]),
        ("source_symbol_ids", ["pine:function:math.exp#canonical"]),
        ("version_availability", [5]),
        ("version_availability", [True]),
        ("disposition", "TARGET_DELEGATED"),
        ("call_form", "namespace_function"),
    ],
)
def test_historical_row_requires_exact_audited_producer_contract(tmp_path, field, value):
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_HISTORICAL_BINDINGS"):
        load_mutated(tmp_path, lambda manifest: exp_row(manifest, True).update({field: value}))


@pytest.mark.parametrize(
    "forms",
    [None, [], "FUNCTION", ["UNKNOWN"], ["METHOD"], ["FUNCTION", "FUNCTION"], [["FUNCTION"]]],
)
def test_explicit_producer_call_forms_are_validated(tmp_path, forms):
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_TARGET_CALL_FORMS"):
        load_mutated(tmp_path, lambda manifest: exp_row(manifest).update(producer_call_forms=forms))


def test_conflicting_historical_projection_does_not_merge_versions_or_parameters(tmp_path):
    def mutate(manifest):
        conflicting = deepcopy(exp_row(manifest, True))
        conflicting["version_availability"] = [4]
        conflicting["parameter_bindings"][0]["source"] = "number"
        manifest["historical_call_bindings"].append(conflicting)

    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_TARGET_DUPLICATE"):
        load_mutated(tmp_path, mutate)


def test_modern_namespace_projection_cannot_silently_replace_historical_parameter_map(tmp_path):
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_TARGET_DUPLICATE"):
        load_mutated(tmp_path, lambda manifest: exp_row(manifest).pop("producer_call_forms"))


def test_unbound_abi_parameter_remains_a_compilation_error(tmp_path):
    def mutate(manifest):
        exp_row(manifest)["parameter_bindings"] = [
            {"abi_parameter": "value", "binding": "UNBOUND_FAIL_CLOSED", "source": None}
        ]

    target = load_mutated(tmp_path, mutate)
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_UNBOUND_PARAMETER"):
        compile_consumer_bundle(
            build_consumer_bundle('//@version=6\nindicator("x")\nplot(math.exp(1))\n'),
            target=target,
        )
