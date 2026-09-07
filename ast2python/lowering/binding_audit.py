"""Read-only structural audits of the exact PineLib emitter's argument contract."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from inspect import Parameter, signature

from ast2python.lowering.target import TargetCallBinding


def audit_pinelib_call_binding(
    binding: TargetCallBinding,
    source_parameters: object,
    *,
    pine_version: int,
) -> tuple[str, ...]:
    """Check producer argument coverage and the ABI keywords emitted by `_call`.

    Empty findings mean only that the structural argument mapping is complete.
    They do not certify value types, qualifiers, return values, state/lifecycle,
    or host execution. Findings ending in ``_UNVERIFIED`` require call-specific
    IR or metadata absent from a catalogue signature. This helper never invokes
    a builtin, infers a source alias, or supplies an omitted required argument.
    """
    reasons: set[str] = set()
    if type(pine_version) is not int or pine_version not in binding.supported_pine_versions:
        reasons.add("A2P_TARGET_CALL_BINDING")
    if binding.disposition == "TARGET_DELEGATED":
        # The emitter forwards producer arguments verbatim to the exact host
        # identity. The host owner must separately check handler availability.
        if not all(
            isinstance(value, str) and value
            for value in (
                binding.delegation_owner,
                binding.delegation_schema_id,
                binding.delegation_capability_id,
            )
        ):
            reasons.add("A2P_PINELIB_CALL_DELEGATION")
        return tuple(sorted(reasons))
    if binding.disposition != "TARGET_DIRECT":
        return tuple(sorted(reasons | {"A2P_PINELIB_BINDING_DISPOSITION_UNVERIFIED"}))
    if not isinstance(source_parameters, (list, tuple)):
        return tuple(sorted(reasons | {"A2P_PINELIB_SOURCE_SIGNATURE_UNVERIFIED"}))
    names: set[str] = set()
    for parameter in source_parameters:
        if (
            not isinstance(parameter, Mapping)
            or not isinstance(parameter.get("name"), str)
            or not parameter["name"]
            or parameter["name"] in names
            or parameter.get("variadic")
        ):
            return tuple(sorted(reasons | {"A2P_PINELIB_SOURCE_SIGNATURE_UNVERIFIED"}))
        names.add(parameter["name"])
    if not names and binding.parameters:
        # Some generic catalogue entries omit their context-derived arguments.
        reasons.add("A2P_PINELIB_SOURCE_SIGNATURE_UNVERIFIED")
    if binding.state_model == "ADMITTED_INPUT":
        # Input arguments are consumed by metadata admission, not normal _call.
        return tuple(sorted(reasons | {"A2P_PINELIB_INPUT_METADATA_UNVERIFIED"}))
    try:
        if binding.python_module is None:
            raise ValueError("missing exact module")
        function = getattr(import_module(binding.python_module), binding.python_name)
        abi = signature(function).parameters
    except (ImportError, AttributeError, TypeError, ValueError):
        return tuple(sorted(reasons | {"A2P_PINELIB_ABI_SIGNATURE_UNVERIFIED"}))
    if any(p.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD) for p in abi.values()):
        reasons.add("A2P_PINELIB_ABI_SIGNATURE_UNVERIFIED")

    supplied: set[str] = set()
    consumed: set[str] = set()
    mapped: set[str] = set()
    for parameter_binding in binding.parameter_bindings:
        if not isinstance(parameter_binding, Mapping):
            reasons.add("A2P_PINELIB_PARAMETER_BINDING")
            continue
        name = parameter_binding.get("abi_parameter")
        kind = parameter_binding.get("binding")
        source = parameter_binding.get("source")
        if not isinstance(name, str) or name not in abi or name in mapped:
            reasons.add("A2P_PINELIB_PARAMETER_BINDING")
            continue
        mapped.add(name)
        if kind == "SOURCE_PARAMETER":
            if isinstance(source, str) and source in names:
                consumed.add(source)
                supplied.add(name)
            # The emitter omits a source argument absent from this overload.
            # Required ABI parameters are checked below; optional defaults work.
        elif kind == "ABI_DEFAULT":
            pass
        elif kind == "UNBOUND_FAIL_CLOSED":
            reasons.add("A2P_PINELIB_UNBOUND_PARAMETER")
        elif kind == "METHOD_RECEIVER":
            if binding.call_form != "METHOD":
                reasons.add("A2P_PINELIB_METHOD_RECEIVER")
            else:
                supplied.add(name)
        elif kind != "INJECTED":
            reasons.add("A2P_PINELIB_PARAMETER_BINDING")
        elif source == "COMPILED_REQUEST_EXPRESSION":
            if "expression" not in names:
                reasons.add("A2P_PINELIB_SOURCE_PARAMETER")
            else:
                consumed.add("expression")
                supplied.add(name)
        elif source == "REQUEST_TIMEFRAME_ARGUMENT":
            timeframe = names & {"timeframe", "resolution"}
            if len(timeframe) != 1 or (pine_version >= 5 and "resolution" in timeframe):
                reasons.add("A2P_REQUEST_TIMEFRAME")
            else:
                consumed.update(timeframe)
                supplied.add(name)
        elif isinstance(source, str) and source in {
            "RUNTIME_TRANSACTION",
            "SOURCE_LOCATION_STATE_ID",
            "SOURCE_LOCATION_OBJECT_ID",
            "SOURCE_SPAN",
            "SEMANTIC_RETURN_TYPE",
        }:
            supplied.add(name)
        elif source == "SEMANTIC_TYPE_DESCRIPTOR":
            supplied.add(name)
            reasons.add("A2P_PINELIB_TYPE_DESCRIPTOR_UNVERIFIED")
        else:
            reasons.add("A2P_PINELIB_INJECTION")
    if names - consumed:
        reasons.add("A2P_PINELIB_SOURCE_PARAMETER")
    for name, parameter in abi.items():
        if parameter.kind == Parameter.POSITIONAL_ONLY and name in supplied:
            reasons.add("A2P_PINELIB_PARAMETER_BINDING")
        if (
            parameter.kind not in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
            and parameter.default is Parameter.empty
            and name not in supplied
        ):
            reasons.add("A2P_PINELIB_UNBOUND_PARAMETER")
    return tuple(sorted(reasons))
