from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ast2python.diagnostics import SourceLocation
from ast2python.errors import ValidationError


def _as_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"AST node must be a mapping, got {type(value).__name__}")
    return value


def _span_to_loc(span: dict[str, Any]) -> SourceLocation:
    if "start" in span or "end" in span:
        start = span.get("start", {})
        end = span.get("end", {})
        return SourceLocation(
            line=start.get("line"),
            column=start.get("column"),
            end_line=end.get("line"),
            end_column=end.get("column"),
        )
    return SourceLocation(
        line=span.get("start_line") or span.get("line"),
        column=span.get("start_col") or span.get("column"),
        end_line=span.get("end_line"),
        end_column=span.get("end_col"),
    )


@dataclass(frozen=True)
class ASTNode:
    raw: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.raw.get("kind") or self.raw.get("type") or "Unknown")

    @property
    def source(self) -> str | None:
        source = self.raw.get("source")
        if isinstance(source, str) and source:
            return source
        return None

    @property
    def loc(self) -> SourceLocation | None:
        span = self.raw.get("span") or self.raw.get("loc")
        if isinstance(span, dict):
            return _span_to_loc(span)
        return None

    def child(self, key: str) -> ASTNode | None:
        value = self.raw.get(key)
        if isinstance(value, dict):
            return ASTNode(value)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return ASTNode(value[0])
        return None

    def field(self, *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in self.raw:
                return self.raw[key]
        return default

    def children(self, *keys: str) -> list[ASTNode]:
        values: list[ASTNode] = []
        for key in keys:
            raw_value = self.raw.get(key)
            if isinstance(raw_value, dict):
                if key == "body" and isinstance(raw_value.get("statements"), list):
                    values.extend(ASTNode(item) for item in raw_value["statements"] if isinstance(item, dict))
                else:
                    values.append(ASTNode(raw_value))
            elif isinstance(raw_value, list):
                values.extend(ASTNode(item) for item in raw_value if isinstance(item, dict))
        return values

    def descendants(self) -> Iterable[ASTNode]:
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            for value in node.raw.values():
                if isinstance(value, dict):
                    stack.append(ASTNode(value))
                elif isinstance(value, list):
                    for item in reversed(value):
                        if isinstance(item, dict):
                            stack.append(ASTNode(item))


@dataclass(frozen=True)
class ASTProgram(ASTNode):
    @property
    def items(self) -> list[ASTNode]:
        return self.children("items", "children", "body")

    @property
    def declaration(self) -> ASTNode | None:
        return self.child("declaration")


def ensure_program_node(value: dict[str, Any]) -> ASTProgram:
    node = ASTProgram(_as_mapping(value))
    if node.kind != "Program":
        raise ValidationError(f"Expected Program node, got {node.kind}")
    return node


def validate_ast(program: ASTProgram) -> list[str]:
    problems: list[str] = []
    if program.field("language") not in {None, "pine"}:
        problems.append("language must be 'pine'")
    if program.declaration is None:
        problems.append("Program must contain a declaration")
    for node in program.descendants():
        if not node.kind:
            problems.append("Node kind/type is required")
            break
    return problems


def load_ast(path: str | Path) -> ASTProgram:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ensure_program_node(_as_mapping(data))
