from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class SourceLocation:
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    @property
    def source_map(self) -> str | None:
        if self.line is None:
            return None
        return f"L{self.line}"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: Severity
    location: SourceLocation | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "location": None if self.location is None else self.location.__dict__,
            "details": self.details or {},
        }


CONTRACT_VERSION_MISMATCH = "P2A_CONTRACT_VERSION_MISMATCH"
UNKNOWN_OVERLOAD = "P2A_UNKNOWN_OVERLOAD"
UNSUPPORTED_DECLARATION_ARG = "P2A_UNSUPPORTED_DECLARATION_ARG"
WARNING_NESTED_SECURITY = "P2A_WARNING_NESTED_SECURITY"
VISUAL_OBJECT_USED_AS_VALUE = "P2A_VISUAL_OBJECT_USED_AS_VALUE"
MISSING_LOC_STATE_ID_HASH = "P2A_MISSING_LOC_STATE_ID_HASH"
BOOL_NA_OVERLOAD = "P2A_BOOL_NA_OVERLOAD"
NESTED_REQUEST_SECURITY = "P2A_NESTED_REQUEST_SECURITY"
REQUEST_SECURITY_CAPTURE_UNSAFE = "P2A_REQUEST_SECURITY_CAPTURE_UNSAFE"
REFERENCE_HISTORY_UNSUPPORTED = "P2A_REFERENCE_HISTORY_UNSUPPORTED"
REFERENCE_COPY_POLICY = "P2A_REFERENCE_COPY_POLICY"
UNSUPPORTED_NODE = "P2A_UNSUPPORTED_NODE"
EXTERNAL_LIBRARY_CALL = "P2A_EXTERNAL_LIBRARY_CALL"
UNSUPPORTED_REQUEST = "P2A_UNSUPPORTED_REQUEST"
