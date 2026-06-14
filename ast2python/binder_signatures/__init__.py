"""Machine-readable builtin signature fragments grouped by Pine namespace."""

from __future__ import annotations

from typing import Any

__all__ = ["BUILTIN_SIGNATURES"]


def __getattr__(name: str) -> Any:
    if name == "BUILTIN_SIGNATURES":
        from ast2python.binder_registry import BUILTIN_SIGNATURES

        return BUILTIN_SIGNATURES
    raise AttributeError(name)
