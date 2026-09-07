"""Compiler-owned structural audit: findings agree with exact emission gates."""

from dataclasses import replace

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

from ast2python import compile_consumer_bundle
from ast2python.errors import BundleInvariantError
from ast2python.lowering import (
    audit_pinelib_call_binding,
    audit_pinelib_value_binding,
    load_pinelib_target_manifest,
)


def binding(symbol, form="NAMESPACE_FUNCTION", overload="canonical"):
    return load_pinelib_target_manifest().call_bindings[(symbol, symbol + "#" + overload, form)]


def audit(row, names, version=6):
    return audit_pinelib_call_binding(row, [{"name": name} for name in names], pine_version=version)


@pytest.mark.parametrize("version", range(1, 7))
def test_scalar_source_names_and_runtime_transaction_state_injections(version):
    form = "NAMESPACE_FUNCTION" if version >= 5 else "FUNCTION"
    assert not audit(
        binding("pine:function:math.sqrt", form), ["number" if version >= 5 else "x"], version
    )
    assert not audit(binding("pine:function:ta.sma", form), ["source", "length"], version)


def test_stale_source_name_and_missing_producer_argument_are_definite_failures():
    original = binding("pine:function:math.sqrt")
    stale = replace(
        original,
        parameter_bindings=(
            {"abi_parameter": "value", "binding": "SOURCE_PARAMETER", "source": "ghost"},
        ),
    )
    assert set(audit(stale, ["number"])) == {
        "A2P_PINELIB_SOURCE_PARAMETER",
        "A2P_PINELIB_UNBOUND_PARAMETER",
    }
    assert "A2P_PINELIB_SOURCE_PARAMETER" in audit(original, ["number", "new_argument"])
    target = load_pinelib_target_manifest()
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_SOURCE_PARAMETER"):
        compile_consumer_bundle(
            build_consumer_bundle('//@version=6\nindicator("x")\nplot(math.sqrt(4))\n'),
            target=replace(target, call_bindings={**target.call_bindings, stale.key: stale}),
        )


def test_extra_optional_source_mapping_and_explicit_abi_default_are_permitted():
    row = binding("pine:function:math.round")
    assert not audit(row, ["number"])
    assert not audit(row, ["number", "precision"])
    default = replace(
        row,
        parameter_bindings=(
            row.parameter_bindings[0],
            {"abi_parameter": "precision", "binding": "ABI_DEFAULT", "source": None},
        ),
    )
    assert not audit(default, ["number"])
    # If a producer can supply precision, silently dropping it is a real error.
    assert "A2P_PINELIB_SOURCE_PARAMETER" in audit(default, ["number", "precision"])


def test_required_abi_argument_cannot_be_omitted_or_given_a_nonexistent_default():
    row = binding("pine:function:math.sqrt")
    for mappings in ((), ({"abi_parameter": "value", "binding": "ABI_DEFAULT", "source": None},)):
        assert "A2P_PINELIB_UNBOUND_PARAMETER" in audit(
            replace(row, parameter_bindings=mappings), ["number"]
        )


@pytest.mark.parametrize("version", range(1, 7))
def test_request_expression_and_exact_versioned_timeframe_use_existing_route(version):
    form = "NAMESPACE_FUNCTION" if version >= 5 else "FUNCTION"
    row = binding("pine:function:request.security", form)
    names = ["symbol", "timeframe" if version >= 5 else "resolution", "expression", "gaps"]
    if version >= 3:
        names.append("lookahead")
    assert not audit(row, names, version)


def test_request_timeframe_and_expression_must_be_present_unambiguously():
    row = binding("pine:function:request.security")
    for names in (
        ["symbol", "expression"],
        ["symbol", "resolution", "expression"],
        ["symbol", "timeframe", "resolution", "expression"],
    ):
        assert "A2P_REQUEST_TIMEFRAME" in audit(row, names)
    assert "A2P_PINELIB_SOURCE_PARAMETER" in audit(row, ["symbol", "timeframe"])


def test_method_receiver_is_injected_only_for_method_form():
    row = binding("pine:method:array.get", "METHOD")
    assert not audit(row, ["index"])
    assert "A2P_PINELIB_METHOD_RECEIVER" in audit(replace(row, call_form="FUNCTION"), ["index"])


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "unknown_abi", "unknown_injection"])
def test_invalid_keyword_or_injection_mechanism_does_not_claim_a_binding(fault):
    row = binding("pine:function:math.sqrt")
    mappings = [dict(row.parameter_bindings[0])]
    if fault == "duplicate":
        mappings.append(dict(mappings[0]))
    elif fault == "unknown_abi":
        mappings[0]["abi_parameter"] = "ghost"
    elif fault == "unknown_injection":
        mappings[0].update(binding="INJECTED", source="UNKNOWN_COMPILER_CONTEXT")
    else:
        mappings[0]["binding"] = "UNKNOWN_BINDING_KIND"
    assert audit(replace(row, parameter_bindings=tuple(mappings)), ["number"])


def test_absent_dynamic_source_signature_and_context_sensitive_rules_remain_unverified():
    row = binding("pine:method:array.get", "METHOD")
    assert "A2P_PINELIB_SOURCE_SIGNATURE_UNVERIFIED" in audit(row, [])
    scalar = binding("pine:function:math.sqrt")
    typed = replace(
        scalar,
        parameter_bindings=(
            {"abi_parameter": "value", "binding": "INJECTED", "source": "SEMANTIC_TYPE_DESCRIPTOR"},
        ),
        parameters=(),
    )
    assert audit(typed, []) == ("A2P_PINELIB_TYPE_DESCRIPTOR_UNVERIFIED",)
    assert "A2P_PINELIB_INPUT_METADATA_UNVERIFIED" in audit(
        replace(scalar, state_model="ADMITTED_INPUT"), ["number"]
    )


@pytest.mark.parametrize("version", range(1, 7))
def test_exact_strategy_delegate_preserves_host_owned_validation(version):
    row = binding("pine:function:strategy.entry")
    assert not audit(row, ["id", "direction"], version)
    assert "A2P_PINELIB_CALL_DELEGATION" in audit(
        replace(row, delegation_owner=None), ["id", "direction"], version
    )


@pytest.mark.parametrize("version", range(1, 7))
def test_runtime_value_transaction_and_zero_argument_constant_are_structurally_bound(version):
    target = load_pinelib_target_manifest()
    for symbol in ("pine:variable:close", "pine:constant:barmerge.gaps_off"):
        assert not audit_pinelib_value_binding(target.value_bindings[symbol], pine_version=version)


@pytest.mark.parametrize(
    "kind,source",
    [
        ("INJECTED", "SOURCE_SPAN"),
        ("INJECTED", "SOURCE_LOCATION_STATE_ID"),
        ("INJECTED", "SEMANTIC_RETURN_TYPE"),
        ("INJECTED", "COMPILED_REQUEST_EXPRESSION"),
        ("INJECTED", "REQUEST_TIMEFRAME_ARGUMENT"),
        ("METHOD_RECEIVER", "receiver"),
        ("SOURCE_PARAMETER", "x"),
    ],
)
def test_value_injections_do_not_inherit_general_call_injection_support(kind, source):
    target = load_pinelib_target_manifest()
    original = target.value_bindings["pine:variable:close"]
    wrong = replace(
        original, parameter_bindings=({"abi_parameter": "tx", "binding": kind, "source": source},)
    )
    assert "A2P_PINELIB_VALUE_PARAMETER_BINDING" in audit_pinelib_value_binding(
        wrong, pine_version=6
    )
    with pytest.raises(BundleInvariantError, match="A2P_PINELIB_VALUE_PARAMETER_BINDING"):
        compile_consumer_bundle(
            build_consumer_bundle('//@version=6\nindicator("value")\nplot(close)\n'),
            target=replace(
                target, value_bindings={**target.value_bindings, original.symbol_id: wrong}
            ),
        )


@pytest.mark.parametrize(
    "mappings",
    [
        (),
        ({"abi_parameter": "tx", "binding": "ABI_DEFAULT", "source": None},),
        ({"abi_parameter": "tx", "binding": "UNBOUND_FAIL_CLOSED", "source": None},),
    ],
)
def test_value_required_transaction_cannot_be_omitted_or_defaulted(mappings):
    original = load_pinelib_target_manifest().value_bindings["pine:variable:close"]
    wrong = replace(original, parameter_bindings=mappings)
    assert "A2P_PINELIB_UNBOUND_VALUE_PARAMETER" in audit_pinelib_value_binding(
        wrong, pine_version=6
    )


@pytest.mark.parametrize("fault", ["duplicate", "unknown_keyword", "unknown_kind"])
def test_value_abi_keyword_identity_and_binding_kind_are_checked(fault):
    original = load_pinelib_target_manifest().value_bindings["pine:variable:close"]
    mappings = [dict(original.parameter_bindings[0])]
    if fault == "duplicate":
        mappings.append(dict(mappings[0]))
    elif fault == "unknown_keyword":
        mappings[0]["abi_parameter"] = "ghost"
    else:
        mappings[0]["binding"] = "UNKNOWN"
    wrong = replace(original, parameter_bindings=tuple(mappings))
    assert "A2P_PINELIB_VALUE_PARAMETER_BINDING" in audit_pinelib_value_binding(
        wrong, pine_version=6
    )


@pytest.mark.parametrize("version", range(1, 7))
def test_value_delegation_requires_exact_host_identity_and_version(version):
    row = load_pinelib_target_manifest().value_bindings["pine:variable:strategy.position_size"]
    assert not audit_pinelib_value_binding(row, pine_version=version)
    assert "A2P_PINELIB_VALUE_DELEGATION" in audit_pinelib_value_binding(
        replace(row, delegation_owner=None), pine_version=version
    )
    assert "A2P_PINELIB_VALUE_VERSION" in audit_pinelib_value_binding(
        replace(row, supported_pine_versions=()), pine_version=version
    )


def test_missing_or_unsupported_value_callable_cannot_be_certified():
    row = load_pinelib_target_manifest().value_bindings["pine:variable:close"]
    assert audit_pinelib_value_binding(replace(row, python_module=None), pine_version=6) == (
        "A2P_PINELIB_VALUE_CALLABLE",
    )
    assert audit_pinelib_value_binding(
        replace(row, python_name="missing_value_callable"), pine_version=6
    ) == ("A2P_PINELIB_VALUE_ABI_SIGNATURE_UNVERIFIED",)
    assert audit_pinelib_value_binding(
        replace(row, disposition="UNSUPPORTED_FAIL_CLOSED"), pine_version=6
    ) == ("A2P_PINELIB_VALUE_UNSUPPORTED",)
