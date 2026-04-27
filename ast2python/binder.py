from __future__ import annotations

from dataclasses import dataclass

from ast2python.types import QUALIFIER_ORDER, TypeInfo


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    accepted_types: frozenset[str]
    qualifier_max: str = "series"
    required: bool = True


@dataclass(frozen=True)
class SignatureSpec:
    builtin: str
    parameters: tuple[ParameterSpec, ...]
    allow_extra_named: frozenset[str] = frozenset()


NUMERIC = frozenset({"int", "float", "source"})
ANY = frozenset({"any", "object", "int", "float", "bool", "string", "color", "PineObjectId"})


# Deliberately small, high-confidence foundation. Unknown matrix entries must be
# explicit diagnostics, not silently generated code that may diverge from Pine.
BUILTIN_SIGNATURES: dict[str, SignatureSpec] = {
    "ta.ema": SignatureSpec(
        "ta.ema",
        (
            ParameterSpec("source", NUMERIC, "series"),
            ParameterSpec("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.rma": SignatureSpec(
        "ta.rma",
        (
            ParameterSpec("source", NUMERIC, "series"),
            ParameterSpec("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.rsi": SignatureSpec(
        "ta.rsi",
        (
            ParameterSpec("source", NUMERIC, "series"),
            ParameterSpec("length", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.atr": SignatureSpec("ta.atr", (ParameterSpec("length", frozenset({"int"}), "simple"),)),
    "ta.sma": SignatureSpec(
        "ta.sma",
        (
            ParameterSpec("source", NUMERIC, "series"),
            # Pine's sma length surface is more permissive across versions than ema;
            # keep this matrix permissive until oracle fixtures pin the exact overload.
            ParameterSpec("length", frozenset({"int"}), "series"),
        ),
    ),
    "ta.bb": SignatureSpec(
        "ta.bb",
        (
            ParameterSpec("series", NUMERIC, "series"),
            ParameterSpec("length", frozenset({"int"}), "series"),
            ParameterSpec("mult", NUMERIC, "simple"),
        ),
    ),
    "ta.macd": SignatureSpec(
        "ta.macd",
        (
            ParameterSpec("source", NUMERIC, "series"),
            ParameterSpec("fastlen", frozenset({"int"}), "simple"),
            ParameterSpec("slowlen", frozenset({"int"}), "simple"),
            ParameterSpec("siglen", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.supertrend": SignatureSpec(
        "ta.supertrend",
        (
            ParameterSpec("factor", NUMERIC, "series"),
            ParameterSpec("atrPeriod", frozenset({"int"}), "simple"),
        ),
    ),
    "ta.crossover": SignatureSpec(
        "ta.crossover",
        (ParameterSpec("source1", NUMERIC, "series"), ParameterSpec("source2", NUMERIC, "series")),
    ),
    "ta.crossunder": SignatureSpec(
        "ta.crossunder",
        (ParameterSpec("source1", NUMERIC, "series"), ParameterSpec("source2", NUMERIC, "series")),
    ),
    "ta.cross": SignatureSpec(
        "ta.cross",
        (ParameterSpec("source1", NUMERIC, "series"), ParameterSpec("source2", NUMERIC, "series")),
    ),
}


def qualifier_leq(actual: str, maximum: str) -> bool:
    return QUALIFIER_ORDER.get(actual, 99) <= QUALIFIER_ORDER.get(maximum, 99)


def type_matches(actual: str, accepted: frozenset[str]) -> bool:
    if "any" in accepted:
        return True
    if actual in accepted:
        return True
    if actual == "object":
        return "object" in accepted or "any" in accepted
    return actual == "int" and "float" in accepted


def bind_builtin_call(
    builtin: str,
    arg_types: list[tuple[str | None, TypeInfo]],
) -> list[str]:
    """Return human-readable binding errors for a known builtin call."""
    spec = BUILTIN_SIGNATURES.get(builtin)
    if spec is None:
        return [f"{builtin} has no AST2Python semantic binder signature"]
    errors: list[str] = []
    required = sum(1 for param in spec.parameters if param.required)
    if len(arg_types) < required:
        errors.append(f"{builtin} expects at least {required} arguments, got {len(arg_types)}")
    if len(arg_types) > len(spec.parameters):
        errors.append(f"{builtin} expects at most {len(spec.parameters)} arguments, got {len(arg_types)}")
    name_to_index = {param.name: index for index, param in enumerate(spec.parameters)}
    used: set[int] = set()
    for index, (arg_name, actual) in enumerate(arg_types):
        param_index = index
        if arg_name is not None:
            if arg_name in name_to_index:
                param_index = name_to_index[arg_name]
            elif arg_name in spec.allow_extra_named:
                continue
            else:
                errors.append(f"{builtin} does not accept named argument {arg_name!r}")
                continue
        if param_index >= len(spec.parameters):
            continue
        if param_index in used:
            errors.append(f"{builtin} argument {spec.parameters[param_index].name!r} is provided more than once")
            continue
        used.add(param_index)
        expected = spec.parameters[param_index]
        if not type_matches(actual.base_type, expected.accepted_types):
            accepted = "/".join(sorted(expected.accepted_types))
            errors.append(
                f"{builtin}.{expected.name} expects {accepted}, got {actual.base_type}"
            )
        if not qualifier_leq(actual.qualifier, expected.qualifier_max):
            errors.append(
                f"{builtin}.{expected.name} expects qualifier <= {expected.qualifier_max}, got {actual.qualifier}"
            )
    return errors
