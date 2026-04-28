from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ast2python.diagnostics import SourceLocation


@dataclass(frozen=True)
class SourceMapEntry:
    python_line: int
    pine_line: int | None
    pine_column: int | None
    pine_end_line: int | None
    pine_end_column: int | None
    pine_source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "python_line": self.python_line,
            "pine_line": self.pine_line,
            "pine_column": self.pine_column,
            "pine_end_line": self.pine_end_line,
            "pine_end_column": self.pine_end_column,
            "pine_source": self.pine_source,
        }


@dataclass
class SourceMapBuilder:
    entries: list[SourceMapEntry] = field(default_factory=list)

    def add(
        self, python_line: int, location: SourceLocation | None, pine_source: str | None = None
    ) -> None:
        self.entries.append(
            SourceMapEntry(
                python_line=python_line,
                pine_line=None if location is None else location.line,
                pine_column=None if location is None else location.column,
                pine_end_line=None if location is None else location.end_line,
                pine_end_column=None if location is None else location.end_column,
                pine_source=pine_source,
            )
        )

    def to_list(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.entries]
