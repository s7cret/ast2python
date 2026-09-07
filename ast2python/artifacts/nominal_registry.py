"""Admit a nominal registry from an already verified generated module.

The caller must first verify the emitted module bytes against the envelope's
``emitted_module_hash``, then execute those bytes and pass their namespace here
before running any callback or restoring a checkpoint. A namespace alone cannot
prove which bytes produced it. This helper revalidates the complete envelope;
it does not replace that module verification or establish source authenticity.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ast2python.artifacts.generated import verify_generated_artifact_v3
from ast2python.errors import BundleInvariantError

if TYPE_CHECKING:
    from pinelib.reference.registry import NominalTypeRegistry

_REGISTRY_CAPABILITY = "compiler.nominal_registry.v1"
_NOMINAL_CAPABILITY = "compiler.nominal_types.v1"
_LITERAL = "NOMINAL_TYPE_REGISTRY"


def admitted_nominal_registry(
    namespace: Mapping[str, Any], envelope: Mapping[str, Any]
) -> NominalTypeRegistry | None:
    """Return the immutable runtime owner, or explicit legacy nonnominal absence.

    Pine v5/v6 registry literals require the exact registry capability. Earlier
    nominal artifacts require recompilation; their declarations must never be
    learned from values or callbacks. Pine v1-v4 only retain the legacy path
    with neither a nominal capability nor a registry literal. Runtime owns all
    registry shape, identity, declaration closure, and membership validation.
    """
    verify_generated_artifact_v3(envelope)
    capabilities = envelope["required_capabilities"]
    has_literal = _LITERAL in namespace
    requires_registry = _REGISTRY_CAPABILITY in capabilities
    requires_nominal = _NOMINAL_CAPABILITY in capabilities
    if not has_literal and not requires_registry and not requires_nominal:
        return None

    version = envelope["version_context"]["pine_version"]
    if version < 5:
        raise BundleInvariantError(
            "A2P_NOMINAL_REGISTRY_VERSION", "nominal registry admission requires Pine v5/v6"
        )
    if not requires_registry:
        raise BundleInvariantError(
            "A2P_NOMINAL_REGISTRY_CAPABILITY",
            "nominal artifacts require compiler.nominal_registry.v1; recompile the artifact",
        )
    if not has_literal:
        raise BundleInvariantError(
            "A2P_NOMINAL_REGISTRY_MISSING", "generated nominal registry literal is missing"
        )

    # Keep legacy nonnominal admission independent of the optional runtime.
    # from_json freezes its own records; no live namespace containers survive.
    from pinelib.reference.registry import NominalTypeRegistry

    return NominalTypeRegistry.from_json(
        namespace[_LITERAL],
        pine_version=version,
        expected_source_hash=envelope["source_hash"],
    )
