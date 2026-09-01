from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdmissionFinding:
    code: str
    message: str
    path: str = "$"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message, "path": self.path}
        if self.details:
            result["details"] = dict(self.details)
        return result


class BundleAdmissionError(ValueError):
    def __init__(
        self, code: str, message: str, *, path: str = "$", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.finding = AdmissionFinding(code=code, message=message, path=path, details=details)


class BundleSourceError(BundleAdmissionError):
    pass


class BundleLimitError(BundleAdmissionError):
    pass


class BundleInvariantError(BundleAdmissionError):
    pass


class AnalysisOnlyError(RuntimeError):
    """Runnable output was requested from an analysis-only compilation session."""
