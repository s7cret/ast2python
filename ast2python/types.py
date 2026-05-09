from __future__ import annotations

from dataclasses import dataclass

QUALIFIER_ORDER = {"const": 0, "input": 1, "simple": 2, "series": 3}
REFERENCE_TYPES = {"array", "matrix", "map", "UDT", "object", "line", "label", "box", "table"}


@dataclass(frozen=True)
class TypeInfo:
    base_type: str
    qualifier: str
    is_reference_type: bool = False
    can_be_na: bool = True
    is_history_allowed: bool = True
    pine_type_source: str | None = None
    origin: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "base_type": self.base_type,
            "qualifier": self.qualifier,
            "is_reference_type": self.is_reference_type,
            "can_be_na": self.can_be_na,
            "is_history_allowed": self.is_history_allowed,
            "pine_type_source": self.pine_type_source,
            "origin": self.origin,
        }


def normalize_type(base_type: str | None) -> str:
    if base_type in {"integer"}:
        return "int"
    if base_type in {"str"}:
        return "string"
    if base_type in {None, ""}:
        return "object"
    return str(base_type)


def normalize_qualifier(qualifier: str | None, *, is_series: bool = False) -> str:
    if is_series:
        return "series"
    if qualifier in QUALIFIER_ORDER:
        return str(qualifier)
    return "simple"


def join_qualifiers(*qualifiers: str | None) -> str:
    selected = "const"
    for qualifier in qualifiers:
        normalized = normalize_qualifier(qualifier)
        if QUALIFIER_ORDER[normalized] > QUALIFIER_ORDER[selected]:
            selected = normalized
    return selected


def make_type_info(
    base_type: str | None,
    qualifier: str | None,
    *,
    is_series: bool = False,
    can_be_na: bool = True,
    is_history_allowed: bool = True,
    pine_type_source: str | None = None,
    origin: str | None = None,
) -> TypeInfo:
    normalized_type = normalize_type(base_type)
    return TypeInfo(
        base_type=normalized_type,
        qualifier=normalize_qualifier(qualifier, is_series=is_series),
        is_reference_type=normalized_type in REFERENCE_TYPES,
        can_be_na=can_be_na,
        is_history_allowed=is_history_allowed,
        pine_type_source=pine_type_source,
        origin=origin,
    )
