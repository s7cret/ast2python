from __future__ import annotations

from ast2python.binder_model import NUMERIC, QUALIFIER_ORDER, ParameterSpec, SignatureSpec, TypeInfo
from ast2python.binder_registry import BUILTIN_SIGNATURES


def qualifier_leq(actual: str, maximum: str) -> bool:
    return QUALIFIER_ORDER.get(actual, 99) <= QUALIFIER_ORDER.get(maximum, 99)


def type_matches(actual: str, accepted: frozenset[str]) -> bool:
    if "any" in accepted:
        return True
    if actual in accepted:
        return True
    if actual == "object":
        return "object" in accepted or "any" in accepted
    if actual in {"line", "label", "box", "table"} and "PineObjectId" in accepted:
        return True
    if (
        actual in {"PineArray", "PineMap", "PineMatrix"}
        and actual.removeprefix("Pine").lower() in accepted
    ):
        return True
    return actual == "int" and "float" in accepted


def _allows_untyped_numeric_parameter(
    builtin: str, expected: ParameterSpec, actual: TypeInfo
) -> bool:
    # Pine2AST leaves untyped user-function parameters as object/simple. Keep this
    # escape hatch tied to that origin and to the HMA shape that needs it.
    if (
        actual.origin != "untyped_param"
        or actual.base_type != "object"
        or actual.qualifier != "simple"
    ):
        return False
    if builtin == "math.sqrt" and expected.name == "number":
        return True
    if not builtin.startswith("ta."):
        return False
    if expected.name in {"source", "source1", "source2", "series"}:
        return expected.accepted_types <= NUMERIC
    if expected.name in {"length", "fastlen", "slowlen", "siglen"}:
        return expected.accepted_types == frozenset({"int"})
    return False


def _parameter_slots(spec: SignatureSpec, arg_count: int) -> tuple[ParameterSpec, ...]:
    if spec.vararg is None:
        return spec.parameters
    extras = max(0, arg_count - len(spec.parameters))
    return spec.parameters + tuple(spec.vararg for _ in range(extras))


def bind_builtin_call(builtin: str, arg_types: list[tuple[str | None, TypeInfo]]) -> list[str]:
    """Return human-readable binding errors for a known builtin call."""
    spec = BUILTIN_SIGNATURES.get(builtin)
    if spec is None:
        return [f"{builtin} has no AST2Python semantic binder signature"]
    errors: list[str] = []
    required = sum(1 for param in spec.parameters if param.required)
    if len(arg_types) < max(required, spec.min_varargs):
        errors.append(
            f"{builtin} expects at least {max(required, spec.min_varargs)} arguments, got {len(arg_types)}"  # noqa: E501
        )
    # Only count non-extra named args toward the limit; extra named args
    # (in allow_extra_named) are intentionally excluded from parameter count.
    extra_named = spec.allow_extra_named or frozenset()
    non_extra_count = sum(1 for arg_name, _ in arg_types if arg_name not in extra_named)
    if spec.vararg is None and non_extra_count > len(spec.parameters):
        errors.append(
            f"{builtin} expects at most {len(spec.parameters)} arguments, got {len(arg_types)}"  # noqa: E501
        )
    name_to_index = {param.name: index for index, param in enumerate(spec.parameters)}
    slots = _parameter_slots(spec, len(arg_types))
    used: set[int] = set()
    seen_named = False
    for index, (arg_name, actual) in enumerate(arg_types):
        param_index = index
        if arg_name is not None:
            seen_named = True
            if arg_name in name_to_index:
                param_index = name_to_index[arg_name]
            elif arg_name in spec.allow_extra_named:
                continue
            else:
                errors.append(f"{builtin} does not accept named argument {arg_name!r}")
                continue
        elif seen_named:
            errors.append(f"{builtin} positional argument follows named argument")
        if param_index >= len(slots):
            continue
        if param_index in used and spec.vararg is None:
            errors.append(
                f"{builtin} argument {slots[param_index].name!r} is provided more than once"
            )
            continue
        used.add(param_index)
        expected = slots[param_index]
        if not type_matches(
            actual.base_type, expected.accepted_types
        ) and not _allows_untyped_numeric_parameter(builtin, expected, actual):
            accepted = "/".join(sorted(expected.accepted_types))
            errors.append(f"{builtin}.{expected.name} expects {accepted}, got {actual.base_type}")
        if not qualifier_leq(actual.qualifier, expected.qualifier_max):
            errors.append(
                f"{builtin}.{expected.name} expects qualifier <= {expected.qualifier_max}, got {actual.qualifier}"  # noqa: E501
            )
    for index, param in enumerate(spec.parameters):
        if param.required and index not in used and len(arg_types) >= required:
            errors.append(f"{builtin} missing required argument {param.name!r}")
    if not spec.codegen_supported:
        errors.append(
            f"{builtin} is signature-known but unsupported by current AST2Python codegen: {spec.notes}"  # noqa: E501
        )
    return errors
