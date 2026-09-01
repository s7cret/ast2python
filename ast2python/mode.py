from __future__ import annotations

from enum import StrEnum


class CompilationMode(StrEnum):
    """Controls admission strictness, never Pine semantics."""

    PRODUCTION = "PRODUCTION"
    ANALYSIS = "ANALYSIS"

    @classmethod
    def normalize(cls, value: CompilationMode | str) -> CompilationMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).upper())
        except ValueError as exc:
            raise ValueError(f"unsupported compilation mode: {value!r}") from exc
