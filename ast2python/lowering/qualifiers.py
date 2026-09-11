"""Compiler-owned qualifier contracts at the admitted producer/target boundary.

The source producer still owns inference and bundle verification. These checks do
not infer types again, coerce series to simple, or certify numerical semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ast2python.errors import BundleInvariantError

if TYPE_CHECKING:
    from ast2python.lowering.target import TargetCallBinding

_QUALIFIER_RANK = {"const": 0, "input": 1, "simple": 2, "series": 3}


def _known(value: object) -> bool:
    return type(value) is str and value in _QUALIFIER_RANK


def validate_parameter_qualifiers(
    parameters: list[str] | tuple[str, ...], raw: object, *, path: str = "$"
) -> dict[str, str]:
    """Return a detached complete map. Missing is not equivalent to series."""
    if not isinstance(raw, Mapping) or set(raw) != set(parameters):
        raise BundleInvariantError(
            "A2P_TARGET_PARAMETER_QUALIFIERS",
            "qualifier contract must cover exactly the declared source parameters",
            path=path,
        )
    if any(not _known(q) for q in raw.values()):
        raise BundleInvariantError(
            "A2P_TARGET_PARAMETER_QUALIFIERS",
            "unknown parameter qualifier ceiling",
            path=path,
        )
    return {name: raw[name] for name in parameters}


def project_parameter_qualifiers(
    rows: object, *, symbol_id: str
) -> tuple[list[str], dict[str, str]]:
    """Project explicit runtime metadata, including historical and method rows."""
    if not isinstance(rows, list):
        raise BundleInvariantError(
            "A2P_PINELIB_TARGET_QUALIFIERS",
            "exact target must declare its parameter rows",
            details={"symbol_id": symbol_id},
        )
    names: list[str] = []
    qualifiers: dict[str, str] = {}
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or type(row.get("name")) is not str
            or not row["name"]
            or row["name"] in qualifiers
            or not _known(row.get("qualifier_max"))
        ):
            raise BundleInvariantError(
                "A2P_PINELIB_TARGET_QUALIFIERS",
                "each exact source parameter requires a unique name and explicit qualifier_max",
                details={"symbol_id": symbol_id},
            )
        names.append(row["name"])
        qualifiers[row["name"]] = row["qualifier_max"]
    return names, qualifiers


def audit_pinelib_qualifier_binding(
    binding: TargetCallBinding, source_parameters: object, *, pine_version: int
) -> tuple[str, ...]:
    """Audit qualifier-domain inclusion, separately from ABI mapping and types.

    The target must accept every qualifier permitted by the source signature.
    A wider target is valid: producer admission still enforces its narrower rule.
    Context-generated generic signatures remain UNVERIFIED when not supplied.
    """
    reasons: set[str] = set()
    if type(pine_version) is not int or pine_version not in binding.supported_pine_versions:
        reasons.add("A2P_TARGET_CALL_BINDING")
    try:
        target = validate_parameter_qualifiers(binding.parameters, binding.parameter_qualifiers)
    except BundleInvariantError:
        return tuple(sorted(reasons | {"A2P_TARGET_PARAMETER_QUALIFIERS"}))
    if not isinstance(source_parameters, (list, tuple)):
        return tuple(sorted(reasons | {"A2P_SOURCE_QUALIFIERS_UNVERIFIED"}))
    seen = set()
    for parameter in source_parameters:
        if (
            not isinstance(parameter, Mapping)
            or type(parameter.get("name")) is not str
            or not parameter["name"]
            or parameter["name"] in seen
            or not _known(parameter.get("qualifier_max"))
        ):
            reasons.add("A2P_SOURCE_QUALIFIERS_UNVERIFIED")
            continue
        name = parameter["name"]
        seen.add(name)
        target_max = _argument_ceiling(name, target, binding, pine_version)
        if target_max is None:
            reasons.add("A2P_TARGET_QUALIFIER_PARAMETER")
        elif _QUALIFIER_RANK[parameter["qualifier_max"]] > _QUALIFIER_RANK[target_max]:
            reasons.add("A2P_TARGET_QUALIFIER_CONTRACT")
    if not source_parameters and binding.parameters:
        reasons.add("A2P_SOURCE_QUALIFIERS_UNVERIFIED")
    return tuple(sorted(reasons))


def _argument_ceiling(
    name: str, target: Mapping[str, str], binding: TargetCallBinding, pine_version: int
) -> str | None:
    # The existing REQUEST_TIMEFRAME_ARGUMENT injection explicitly consumes
    # resolution in v1-v4 and timeframe in v5-v6. This is not a global alias or a
    # catalogue fallback; unrelated callables cannot acquire this contract.
    if name in target:
        return target[name]
    if (
        pine_version in {1, 2, 3, 4}
        and name == "resolution"
        and "timeframe" in target
        and any(
            row.get("binding") == "INJECTED" and row.get("source") == "REQUEST_TIMEFRAME_ARGUMENT"
            for row in binding.parameter_bindings
        )
    ):
        return target["timeframe"]
    return None


def validate_call_qualifiers(
    call: Mapping[str, Any], binding: TargetCallBinding, *, node_id: str, pine_version: int
) -> None:
    """Check actual supplied arguments against both source and target ceilings.

    Domain inclusion for *all possible* source values is a separate audit. A
    constant in an older broader signature can still be compiled against a
    narrower target, but a series cannot sneak through it. Omitted defaults are
    callee-owned, not new user arguments; required/default shape admission and
    input metadata validation remain with their existing owners.
    """
    target = validate_parameter_qualifiers(binding.parameters, binding.parameter_qualifiers)
    arguments = call.get("arguments")
    if not isinstance(arguments, (list, tuple)):
        raise BundleInvariantError("A2P_CALL_QUALIFIER", "argument evidence must be an array")
    for argument in arguments:
        if not isinstance(argument, Mapping):
            raise BundleInvariantError("A2P_CALL_QUALIFIER", "argument evidence must be an object")
        name = argument.get("parameter_name")
        source_max = argument.get("max_qualifier")
        actual = argument.get("actual_qualifier")
        if type(name) is not str or not name:
            raise BundleInvariantError(
                "A2P_CALL_QUALIFIER", "argument parameter identity is missing"
            )
        target_max = _argument_ceiling(name, target, binding, pine_version)
        details = {
            "node_id": node_id,
            "binding_key": list(binding.key),
            "parameter": name,
            "producer_max": source_max,
            "target_max": target_max,
            "actual_qualifier": actual,
        }
        if target_max is None:
            raise BundleInvariantError(
                "A2P_TARGET_QUALIFIER_PARAMETER",
                "target has no qualifier for source argument",
                details=details,
            )
        if not _known(source_max) or not _known(actual):
            raise BundleInvariantError(
                "A2P_CALL_QUALIFIER",
                "admitted argument qualifier is invalid",
                details=details,
            )
        if _QUALIFIER_RANK[actual] > _QUALIFIER_RANK[source_max]:
            raise BundleInvariantError(
                "A2P_CALL_QUALIFIER",
                "actual argument exceeds its admitted producer ceiling",
                details=details,
            )
        if _QUALIFIER_RANK[actual] > _QUALIFIER_RANK[target_max]:
            raise BundleInvariantError(
                "A2P_TARGET_ARGUMENT_QUALIFIER",
                "actual argument exceeds the exact runtime target ceiling",
                details=details,
            )
