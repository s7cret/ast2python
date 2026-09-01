from __future__ import annotations

from dataclasses import dataclass

from ast2python.admission import AdmittedConsumerBundle
from ast2python.admission.invariants import PineVersionIdentity
from ast2python.errors import AnalysisOnlyError
from ast2python.mode import CompilationMode


@dataclass(frozen=True, slots=True)
class CompilationSession:
    """Immutable compilation identity admitted from one exact Pine2AST bundle."""

    bundle: AdmittedConsumerBundle

    @property
    def mode(self) -> CompilationMode:
        return self.bundle.mode

    @property
    def pine_version(self) -> int:
        return self.bundle.version_context.pine_version

    @property
    def version_context(self) -> PineVersionIdentity:
        return self.bundle.version_context

    def require_production(self) -> None:
        if self.mode is not CompilationMode.PRODUCTION:
            raise AnalysisOnlyError(
                "analysis mode cannot produce a lowering plan, runnable Python, or a sealed artifact"
            )

    def require_runnable_output(self) -> None:
        self.require_production()
