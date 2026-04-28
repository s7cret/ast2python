from __future__ import annotations

from dataclasses import dataclass, field

from ast2python.diagnostics import SourceLocation
from ast2python.source_map import SourceMapBuilder


@dataclass
class CodeEmitter:
    source_map: SourceMapBuilder
    emit_source_comments: bool = True
    indent_unit: str = "    "
    _indent: int = 0
    _lines: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def indent(self) -> None:
        self._indent += 1

    def dedent(self) -> None:
        self._indent = max(0, self._indent - 1)

    def line(
        self, text: str = "", *, loc: SourceLocation | None = None, source: str | None = None
    ) -> None:
        if text:
            self._lines.append(f"{self.indent_unit * self._indent}{text}")
        else:
            self._lines.append("")
        if loc is not None:
            self.source_map.add(self.line_count, loc, pine_source=source)

    def source_comment(self, loc: SourceLocation | None, source: str | None = None) -> None:
        if not self.emit_source_comments or loc is None or loc.line is None:
            return
        suffix = f" {source}" if source else ""
        self.line(f"# pine:L{loc.line}{suffix}")

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"
