from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from ast2python.version import RUNTIME_CONTRACT_VERSION


class RuntimeLike(Protocol):
    contract_version: str

    def begin_bar(self, bar: Any) -> None: ...


class GeneratedScriptBase:
    """Base interface for AST2Python generated modules targeting runtime contract v1.4."""

    required_runtime_contract = RUNTIME_CONTRACT_VERSION
    script_kind = "script"

    def run(self, bars: Iterable[Any]) -> list[dict[str, Any] | None]:
        raise NotImplementedError

    def _process_bar(self, bar: Any) -> None:
        raise NotImplementedError

    def _snapshot(self) -> dict[str, Any]:
        return {}


class GeneratedIndicatorBase(GeneratedScriptBase):
    script_kind = "indicator"


class GeneratedStrategyBase(GeneratedScriptBase):
    script_kind = "strategy"


class GeneratedLibraryBase(GeneratedScriptBase):
    script_kind = "library"
