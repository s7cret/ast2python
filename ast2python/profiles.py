from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CompileProfile:
    name: Literal["production", "diagnostic"]
    allow_external_library_stubs: bool
    allow_unsupported_request_stubs: bool
    allow_invalid_ast: bool
    allow_implicit_version_rewrite: bool = False
    allow_subprocess_fallback: bool = False

    @classmethod
    def production(cls) -> "CompileProfile":
        return cls(
            name="production",
            allow_external_library_stubs=False,
            allow_unsupported_request_stubs=False,
            allow_invalid_ast=False,
        )

    @classmethod
    def diagnostic(
        cls,
        *,
        allow_external_library_stubs: bool = False,
        allow_unsupported_request_stubs: bool = False,
        allow_invalid_ast: bool = False,
    ) -> "CompileProfile":
        return cls(
            name="diagnostic",
            allow_external_library_stubs=allow_external_library_stubs,
            allow_unsupported_request_stubs=allow_unsupported_request_stubs,
            allow_invalid_ast=allow_invalid_ast,
        )

    @classmethod
    def from_options(
        cls,
        name: Literal["production", "diagnostic"],
        *,
        allow_external_library_stubs: bool = False,
        allow_unsupported_request_stubs: bool = False,
        allow_invalid_ast: bool = False,
    ) -> "CompileProfile":
        if name == "production":
            if allow_external_library_stubs or allow_unsupported_request_stubs or allow_invalid_ast:
                raise ValueError("production compile profile forbids unsafe overrides")
            return cls.production()
        if name == "diagnostic":
            return cls.diagnostic(
                allow_external_library_stubs=allow_external_library_stubs,
                allow_unsupported_request_stubs=allow_unsupported_request_stubs,
                allow_invalid_ast=allow_invalid_ast,
            )
        raise ValueError(f"unsupported compile profile: {name}")
