"""Compiler admission receives a host-owned factory; it never imports a runtime."""

import ast
from pathlib import Path

import pytest

from ast2python.artifacts.nominal_registry import admitted_nominal_registry
from ast2python.errors import BundleInvariantError
from tests.test_nominal_registry_admission import (
    ABSENT,
    NOMINAL,
    REGISTRY,
    payload_for,
    sealed_fixture,
)
from tests.test_nominal_registry_admission import (
    compiled as compiled,
)


@pytest.mark.parametrize("version", [5, 6])
def test_factory_receives_exact_verified_identity_and_returns_same_owner(compiled, version):
    payload = payload_for(compiled, version)
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=payload, capabilities=(REGISTRY,)
    )
    owner = object()
    calls = []

    def admit(value, *, pine_version, expected_source_hash):
        calls.append((value, pine_version, expected_source_hash))
        return owner

    actual = admitted_nominal_registry(namespace, envelope, admit_registry=admit)
    assert actual is owner
    assert len(calls) == 1
    assert calls[0][0] is namespace["NOMINAL_TYPE_REGISTRY"]
    assert calls[0][1:] == (version, envelope["source_hash"])


@pytest.mark.parametrize("nominal", [False, True])
def test_factory_is_required_even_when_legacy_path_would_not_use_it(compiled, nominal):
    namespace, envelope, _ = sealed_fixture(
        compiled,
        payload=payload_for(compiled) if nominal else ABSENT,
        capabilities=(REGISTRY,) if nominal else (),
    )
    with pytest.raises(TypeError, match="admit_registry"):
        admitted_nominal_registry(namespace, envelope)


@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("adapter", [None, 0, "factory"])
def test_noncallable_adapter_is_never_silently_accepted(compiled, nominal, adapter):
    namespace, envelope, _ = sealed_fixture(
        compiled,
        payload=payload_for(compiled) if nominal else ABSENT,
        capabilities=(REGISTRY,) if nominal else (),
    )
    with pytest.raises(BundleInvariantError, match="A2P_NOMINAL_REGISTRY_ADAPTER"):
        admitted_nominal_registry(namespace, envelope, admit_registry=adapter)


@pytest.mark.parametrize("version", range(1, 7))
def test_legacy_absence_never_calls_or_loads_a_runtime_factory(compiled, version):
    namespace, envelope, _ = sealed_fixture(compiled, version=version)

    def forbidden(*args, **kwargs):
        pytest.fail("legacy absence must not construct a runtime registry")

    assert admitted_nominal_registry(namespace, envelope, admit_registry=forbidden) is None


@pytest.mark.parametrize(
    "fault,code",
    [
        ("version", "A2P_NOMINAL_REGISTRY_VERSION"),
        ("capability", "A2P_NOMINAL_REGISTRY_CAPABILITY"),
        ("literal", "A2P_NOMINAL_REGISTRY_MISSING"),
        ("old_nominal", "A2P_NOMINAL_REGISTRY_CAPABILITY"),
        ("hash", "A2P_ARTIFACT_HASH"),
        ("envelope", "A2P_ARTIFACT_FIELDS"),
    ],
)
def test_compiler_rejections_precede_any_owner_factory_call(compiled, fault, code):
    version = 4 if fault == "version" else 6
    caps = () if fault == "capability" else ((NOMINAL,) if fault == "old_nominal" else (REGISTRY,))
    literal = ABSENT if fault in {"literal", "old_nominal"} else payload_for(compiled, version)
    namespace, envelope, _ = sealed_fixture(
        compiled, version=version, payload=literal, capabilities=caps
    )
    if fault == "hash":
        envelope["source_hash"] = "sha256:" + "f" * 64
    elif fault == "envelope":
        del envelope["emitted_module_hash"]

    def forbidden(*args, **kwargs):
        pytest.fail("compiler checks must precede owner registry admission")

    with pytest.raises(BundleInvariantError, match=code):
        admitted_nominal_registry(namespace, envelope, admit_registry=forbidden)


def test_owner_error_is_propagated_without_fallback_or_reinterpretation(compiled):
    namespace, envelope, _ = sealed_fixture(
        compiled, payload=payload_for(compiled), capabilities=(REGISTRY,)
    )
    failure = ValueError("runtime owner rejected declaration closure")

    def reject(*args, **kwargs):
        raise failure

    with pytest.raises(ValueError) as caught:
        admitted_nominal_registry(namespace, envelope, admit_registry=reject)
    assert caught.value is failure


def test_wrong_factory_signature_is_not_adapted_by_guessing_arguments(compiled):
    namespace, envelope, _ = sealed_fixture(
        compiled, payload=payload_for(compiled), capabilities=(REGISTRY,)
    )
    with pytest.raises(TypeError, match="pine_version"):
        admitted_nominal_registry(namespace, envelope, admit_registry=lambda payload: object())


def test_admission_module_has_no_runtime_import_or_dynamic_import_escape():
    path = Path(__file__).resolve().parents[1] / "ast2python/artifacts/nominal_registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("pinelib")
        elif isinstance(node, ast.Import):
            assert all(not alias.name.startswith("pinelib") for alias in node.names)
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", None)
            )
            assert name not in {"__import__", "import_module"}
