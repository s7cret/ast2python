from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ast2python.coverage import CoverageTracker
from ast2python.diagnostics import Diagnostic, Severity, SourceLocation
from ast2python.errors import ScopeResolutionError, UnsupportedNodeError
from ast2python.imports import ImportManager
from ast2python.naming import NamingRegistry
from ast2python.source_map import SourceMapBuilder
from ast2python.types import TypeInfo, make_type_info


@dataclass
class VariableInfo:
    pine_name: str
    py_name: str
    type_ref: str | None
    qualifier: str | None
    declaration_kind: str
    is_series: bool
    is_mutable: bool
    scope_id: str
    first_decl_loc: SourceLocation | None = None
    type_info: TypeInfo | None = None


@dataclass
class Scope:
    id: str
    kind: str
    parent_id: str | None
    variables: dict[str, VariableInfo] = field(default_factory=dict)


@dataclass
class TranslationContext:
    variables: dict[str, VariableInfo] = field(default_factory=dict)
    scopes: list[Scope] = field(
        default_factory=lambda: [Scope(id="global", kind="global", parent_id=None)]
    )
    imports: ImportManager = field(default_factory=ImportManager)
    source_map: SourceMapBuilder = field(default_factory=SourceMapBuilder)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    coverage: CoverageTracker = field(default_factory=CoverageTracker)
    naming: NamingRegistry = field(default_factory=NamingRegistry)
    current_function: str | None = None
    current_class: str | None = None
    mode: str = "strategy"
    strict: bool = False
    request_depth: int = 0
    state_id_counts: dict[tuple[int | None, int | None, str], int] = field(default_factory=dict)
    input_metadata: list[dict[str, Any]] = field(default_factory=list)
    strategy_metadata: dict[str, Any] = field(default_factory=dict)
    unsupported_declaration_args: list[str] = field(default_factory=list)
    type_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    import_aliases: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def current_scope(self) -> Scope:
        return self.scopes[-1]

    def enter_scope(self, kind: str) -> Scope:
        scope = Scope(id=f"{kind}_{len(self.scopes)}", kind=kind, parent_id=self.current_scope.id)
        self.scopes.append(scope)
        return scope

    def exit_scope(self) -> None:
        if len(self.scopes) > 1:
            self.scopes.pop()

    def declare_var(
        self,
        name: str,
        *,
        type_ref: str | None,
        qualifier: str | None,
        declaration_kind: str,
        is_series: bool,
        is_mutable: bool,
        loc: SourceLocation | None,
        prefer_py_name: str | None = None,
    ) -> VariableInfo:
        existing = self.current_scope.variables.get(name)
        if existing is not None:
            return existing
        py_name = self.naming.reserve(name, prefer=prefer_py_name)
        type_info = make_type_info(
            type_ref,
            qualifier,
            is_series=is_series,
            pine_type_source=type_ref,
            can_be_na=type_ref != "bool",
        )
        info = VariableInfo(
            pine_name=name,
            py_name=py_name,
            type_ref=type_ref,
            qualifier=qualifier,
            declaration_kind=declaration_kind,
            is_series=is_series,
            is_mutable=is_mutable,
            scope_id=self.current_scope.id,
            first_decl_loc=loc,
            type_info=type_info,
        )
        self.type_metadata[f"{self.current_scope.id}:{name}"] = type_info.to_dict()
        self.current_scope.variables[name] = info
        self.variables[f"{self.current_scope.id}:{name}"] = info
        return info

    def resolve_var(self, name: str) -> VariableInfo:
        for scope in reversed(self.scopes):
            if name in scope.variables:
                return scope.variables[name]
        raise ScopeResolutionError(f"Unknown variable {name!r}")

    def add_diagnostic(
        self,
        code: str,
        message: str,
        severity: Severity,
        *,
        location: SourceLocation | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                severity=severity,
                location=location,
                details=details,
            )
        )

    def unsupported(
        self, node_kind: str, reason: str, *, location: SourceLocation | None = None
    ) -> None:
        self.coverage.unsupported()
        raise UnsupportedNodeError(f"{node_kind}: {reason}")
