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
    min_varargs: int = 0
    vararg: ParameterSpec | None = None
    allow_extra_named: frozenset[str] = frozenset()
    codegen_supported: bool = True
    notes: str = ""


NUMERIC = frozenset({"int", "float", "source"})
NUMERIC_OR_BOOL = frozenset({"int", "float", "bool", "source"})
STRING = frozenset({"string"})
BOOL = frozenset({"bool"})
OBJECT_ID = frozenset({"PineObjectId", "line", "label", "box", "table"})
REFERENCE = frozenset({"array", "map", "matrix", "PineArray", "PineMap", "PineMatrix"})
ANY = frozenset(
    {
        "any",
        "object",
        "int",
        "float",
        "bool",
        "string",
        "color",
        "PineObjectId",
        "array",
        "map",
        "matrix",
    }
)


P = ParameterSpec
S = SignatureSpec


__all__ = [
    "ANY",
    "BOOL",
    "NUMERIC",
    "NUMERIC_OR_BOOL",
    "OBJECT_ID",
    "P",
    "QUALIFIER_ORDER",
    "REFERENCE",
    "S",
    "STRING",
    "TypeInfo",
    "ParameterSpec",
    "SignatureSpec",
]
