"""Preserve exact-target ceilings and check qualifiers before Python emission.

Signature audit and per-invocation admission are separate: a safe literal is not
proof that every input accepted by a producer signature is accepted by its target.
An omitted default has no supplied operand; its producer ceiling is not an actual
value qualifier. Metadata/default evaluation remains owned by the existing emitter.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from ast2python.errors import BundleInvariantError

if TYPE_CHECKING:
    from ast2python.lowering.target import TargetCallBinding, TargetManifest

_RANK = {"const": 0, "input": 1, "simple": 2, "series": 3}
_DECLARATIONS = {"pine:function:" + n for n in ("indicator", "study", "strategy", "library")}


def parse_parameter_qualifiers(
    value: object, parameters: tuple[str, ...], *, required: bool
) -> Mapping[str, str] | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, Mapping)
        or set(value) != set(parameters)
        or any(type(v) is not str or v not in _RANK for v in value.values())
    ):
        raise BundleInvariantError(
            "A2P_TARGET_PARAMETER_QUALIFIERS",
            "exact parameter qualifiers must cover every target parameter without extra names",
        )
    return MappingProxyType(dict(value))


def project_parameter_qualifiers(parameters: object) -> Mapping[str, str]:
    if not isinstance(parameters, (list, tuple)):
        raise BundleInvariantError("A2P_TARGET_PARAMETER_QUALIFIERS", "parameters must be an array")
    qualifiers: dict[str, str] = {}
    for row in parameters:
        if (
            not isinstance(row, Mapping)
            or type(row.get("name")) is not str
            or not row["name"]
            or row["name"] in qualifiers
            or type(row.get("qualifier_max")) is not str
            or row["qualifier_max"] not in _RANK
        ):
            raise BundleInvariantError(
                "A2P_TARGET_PARAMETER_QUALIFIERS", "missing, duplicate or invalid qualifier ceiling"
            )
        qualifiers[row["name"]] = row["qualifier_max"]
    return MappingProxyType(qualifiers)


def qualifier_scope(binding: TargetCallBinding) -> str:
    """The exact emitter, rather than its catalogue label, owns this boundary."""
    if binding.disposition == "TARGET_DELEGATED":
        return "host_delegation"
    if binding.state_model == "ADMITTED_INPUT":
        return "admitted_input_metadata"
    if binding.python_module is None:
        return "reference_target"
    return "direct_runtime"


def _target_parameter(binding: TargetCallBinding, name: str, pine_version: int) -> str:
    # This is the emitter's explicit historical request injection, not a global
    # alias heuristic. Modern requests may not use the legacy spelling.
    if name == "resolution" and pine_version <= 4:
        injected = [row for row in binding.parameter_bindings
                    if row.get("binding") == "INJECTED"
                    and row.get("source") == "REQUEST_TIMEFRAME_ARGUMENT"]
        if len(injected) == 1 and injected[0].get("abi_parameter") == "timeframe":
            return "timeframe"
    return name


def audit_parameter_qualifiers(
    binding: TargetCallBinding, source_parameters: object, *, pine_version: int
) -> tuple[str, ...]:
    """Report signature-wide qualifier compatibility, not runtime equivalence."""
    if type(pine_version) is not int or pine_version not in binding.supported_pine_versions:
        return ("A2P_TARGET_CALL_BINDING",)
    if binding.parameter_qualifiers is None:
        return ("A2P_TARGET_PARAMETER_QUALIFIERS_UNVERIFIED",)
    try:
        source = project_parameter_qualifiers(source_parameters)
    except BundleInvariantError:
        return ("A2P_SOURCE_PARAMETER_QUALIFIERS_UNVERIFIED",)
    reasons: set[str] = set()
    for name, ceiling in source.items():
        target = binding.parameter_qualifiers.get(_target_parameter(binding, name, pine_version))
        if target is None:
            reasons.add("A2P_TARGET_PARAMETER_QUALIFIER_MISSING")
        elif _RANK[ceiling] > _RANK[target]:
            reasons.add("A2P_TARGET_QUALIFIER_CONTRACT")
    return tuple(sorted(reasons))


def validate_plan_argument_qualifiers(
    nodes: Sequence[Mapping[str, Any]], *, target: TargetManifest, pine_version: int
) -> None:
    """Validate serialized IR as well as live plans. No generated code is run."""
    if target.release_acceptance != "EXACT_PINELIB_TARGET_MANIFEST_V2":
        return
    by_id = {node["ir_id"]: node for node in nodes}
    by_source = {node["source"]["node_id"]: node for node in nodes}
    for node in nodes:
        call = node["attributes"].get("call")
        if not isinstance(call, Mapping):
            continue
        symbol = call.get("symbol_id")
        if isinstance(symbol, str) and (symbol.startswith("user:") or symbol in _DECLARATIONS):
            continue
        key = (symbol, call.get("overload_id"), call.get("call_form"))
        if any(type(part) is not str for part in key):
            raise BundleInvariantError("A2P_TARGET_CALL_BINDING", "invalid call identity")
        binding = target.call_bindings.get(key)
        if binding is None or pine_version not in binding.supported_pine_versions:
            raise BundleInvariantError("A2P_TARGET_CALL_BINDING", "missing versioned call binding")
        qualifiers = parse_parameter_qualifiers(
            binding.parameter_qualifiers, binding.parameters, required=True
        )
        assert qualifiers is not None
        if qualifier_scope(binding) != "direct_runtime":
            # Inputs are consumed by the metadata validator; delegated envelopes
            # are checked by their host. Their raw catalogue ceilings are retained
            # and audited, but do not describe ordinary emitted ABI operands.
            continue
        arguments = call.get("arguments", ())
        if not isinstance(arguments, Sequence) or isinstance(arguments, (str, bytes)):
            raise BundleInvariantError("A2P_TARGET_ARGUMENT_QUALIFIER", "invalid call arguments")
        for argument in arguments:
            if not isinstance(argument, Mapping):
                raise BundleInvariantError("A2P_TARGET_ARGUMENT_QUALIFIER", "invalid argument")
            name = argument.get("parameter_name")
            source_id = argument.get("argument_node_id")
            if type(name) is not str or type(source_id) is not str:
                raise BundleInvariantError("A2P_TARGET_ARGUMENT_QUALIFIER", "invalid argument identity")
            argument_node = by_source.get(source_id)
            roles = argument_node["attributes"].get("child_roles", {}) if argument_node else {}
            children = roles.get("value", ()) if isinstance(roles, Mapping) else ()
            local_args = node["attributes"].get("child_roles", {}).get("arguments", ())
            if argument_node is None or argument_node["ir_id"] not in local_args:
                raise BundleInvariantError("A2P_TARGET_ARGUMENT_QUALIFIER", "argument is not owned by its call")
            valid_child = (isinstance(children, (list, tuple)) and len(children) == 1
                           and type(children[0]) is str)
            operand = by_id.get(children[0]) if valid_child else None
            resolved = operand.get("result_type") if operand else None
            actual = resolved.get("qualifier") if isinstance(resolved, Mapping) else None
            claimed = argument.get("actual_qualifier")
            ceiling = qualifiers.get(_target_parameter(binding, name, pine_version))
            details = {
                "node_id": node["source"]["node_id"], "binding_key": list(key),
                "parameter": name, "actual_qualifier": actual,
                "claimed_qualifier": claimed, "target_qualifier_max": ceiling,
                "source_span": dict(node["source"]["span"]),
            }
            if (
                type(actual) is not str or actual not in _RANK or actual != claimed
                or ceiling is None or _RANK[actual] > _RANK[ceiling]
            ):
                raise BundleInvariantError(
                    "A2P_TARGET_ARGUMENT_QUALIFIER",
                    "argument qualifier disagrees with its operand or exceeds the exact target ceiling",
                    details=details,
                )
