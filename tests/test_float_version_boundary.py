"""Source-backed float availability across producer, target audit and execution.

https://www.tradingview.com/pine-script-docs/v4/language/type-system/#type-casting
The declaration predates this change; old successful parsing was not an oracle.
"""

import ast

import pytest
from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pine2ast.semantic.signatures import SignatureResolver
from pinelib import is_na
from pinelib.state.checkpoint import from_portable

from ast2python.lowering import audit_pinelib_call_binding, load_pinelib_target_manifest
from tests.test_rc6_input_metadata import compile_source, run_source


def source(version, body):
    declaration = "study" if version < 5 else "indicator"
    return f'//@version={version}\n{declaration}("float boundary")\n{body}\n'


def float_call_sites(code):
    tree = ast.parse(code)
    aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pinelib.abi.primitives"
        for alias in node.names
        if alias.name == "float_v1"
    }
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in aliases
    ]


@pytest.mark.parametrize("version", range(1, 7))
def test_retained_source_signature_and_target_audit_agree_on_availability(version):
    target = load_pinelib_target_manifest()
    key = ("pine:function:float", "pine:function:float#canonical", "FUNCTION")
    binding = target.call_bindings[key]
    row = CatalogRepository.default().readonly_view(version)["functions"]["float"]
    result = parse_code(source(version, "x=0"))
    resolver = SignatureResolver(version_context=result.ast.version_context)
    candidates = resolver.candidate_entries(row)
    assert len(candidates) == 1  # Unavailable versions remain in the denominator.
    assert binding.supported_pine_versions == (4, 5, 6)
    findings = audit_pinelib_call_binding(
        binding, candidates[0]["parameters"], pine_version=version
    )
    assert resolver.candidate_is_active(candidates[0]) is (version >= 4)
    assert findings == (() if version >= 4 else ("A2P_TARGET_CALL_BINDING",))
    assert "compiler.nominal_registry.v1" in target.capabilities
    assert (
        "pine:function:float",
        "pine:function:float#canonical",
        "NAMESPACE_FUNCTION",
    ) not in target.call_bindings


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("argument", ["na", "1", "x=1.25"])
def test_pre_v4_float_call_cannot_reach_compiler_execution(version, argument):
    code = source(version, f"plot(float({argument}))")
    result = parse_code(code)
    assert not result.ok
    assert any(d.code == "P2A2102" for d in result.diagnostics)
    with pytest.raises(ConsumerBundleError, match="production-blocking diagnostics"):
        compile_source(code)


@pytest.mark.parametrize("version", [4, 5, 6])
def test_admitted_float_positional_named_udf_and_history_values(version):
    runtime, _, compiled = run_source(
        source(
            version,
            "f(x)=>float(x)\nplot(float(close))\nplot(float(x=close))\nplot(f(close))\nplot(float(close[1]))",
        ),
        closes=[0, 1.25, -2],
    )
    actual = [from_portable(event.payload["series"]) for event in runtime.visuals.committed]
    expected = [0.0, 0.0, 0.0, None, 1.25, 1.25, 1.25, 0.0, -2.0, -2.0, -2.0, 1.25]
    assert len(actual) == len(expected)
    for value, wanted in zip(actual, expected, strict=True):
        if wanted is None:
            assert is_na(value)
        else:
            assert type(value) is float
            assert value == wanted
    assert len(float_call_sites(compiled.emitted.code)) == 4


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_literals_promotion_and_user_variable_need_no_cast_binding(version):
    runtime, _, compiled = run_source(
        source(version, "float=2\nplot(float+0.5)\nplot(1e-3)"), closes=[1]
    )
    actual = [from_portable(event.payload["series"]) for event in runtime.visuals.committed]
    assert actual == [2.5, 0.001]
    assert [type(value) for value in actual] == [float, float]
    assert float_call_sites(compiled.emitted.code) == []
