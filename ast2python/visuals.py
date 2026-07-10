from __future__ import annotations

import json
from typing import Any, Literal, TypeAlias, TypeGuard

VisualPolicy: TypeAlias = Literal["drop", "record", "error"]
VISUAL_POLICY_VALUES: tuple[VisualPolicy, ...] = ("drop", "record", "error")

VISUAL_FRONTEND_DIAGNOSTIC_CODES = frozenset({"P2A1507"})
VISUAL_CALLS = frozenset(
    {
        "plot",
        "plotshape",
        "plotchar",
        "hline",
        "fill",
        "bgcolor",
        "barcolor",
    }
)


VISUAL_OBJECT_PREFIXES = ("line.", "label.", "box.", "table.")


def _is_visual_runtime_call(value: str) -> bool:
    return value in VISUAL_CALLS or value.startswith(VISUAL_OBJECT_PREFIXES)


def _visual_runtime_call_from_text(text: str) -> str | None:
    for builtin in sorted(VISUAL_CALLS, key=len, reverse=True):
        if builtin in text:
            return builtin
    for prefix in VISUAL_OBJECT_PREFIXES:
        marker = f"builtin {prefix}"
        start = text.find(marker)
        if start >= 0:
            tail = text[start + len("builtin ") :]
            return tail.split()[0].rstrip(".,:;()")
    return None


def _is_visual_policy(value: str) -> TypeGuard[VisualPolicy]:
    return value in VISUAL_POLICY_VALUES


def normalize_visual_policy(value: str | None) -> VisualPolicy:
    candidate = str(value or "drop").strip().lower().replace("_", "-")
    aliases = {
        "skip": "drop",
        "no-op": "drop",
        "noop": "drop",
        "ignore": "drop",
        "recorder": "record",
        "debug": "record",
        "strict": "error",
        "fail": "error",
    }
    normalized = aliases.get(candidate, candidate)
    if not _is_visual_policy(normalized):
        allowed = ", ".join(VISUAL_POLICY_VALUES)
        raise ValueError(f"unsupported visual policy {value!r}; expected one of: {allowed}")
    return normalized


def frontend_diagnostic_visual_call(item: dict[str, Any]) -> str | None:
    """Return the visual builtin mentioned by a Pine2AST diagnostic, if any.

    Pine2AST runtime-contract diagnostics have changed shape across internal
    milestones, so this intentionally accepts both structured details and the
    human-readable message.  AST2Python only treats these diagnostics as
    ignorable when the caller selected a non-error visual policy.
    """
    details = item.get("details")
    if isinstance(details, dict):
        for key in ("builtin", "name", "callee", "call", "function"):
            value = details.get(key)
            if isinstance(value, str) and _is_visual_runtime_call(value):
                return value
        raw = json.dumps(details, sort_keys=True, default=str)
    else:
        raw = ""
    text = " ".join(
        part
        for part in (
            str(item.get("code", "")),
            str(item.get("message", "")),
            raw,
        )
        if part
    ).lower()
    if item.get("code") in VISUAL_FRONTEND_DIAGNOSTIC_CODES or "runtime-contract" in text:
        return _visual_runtime_call_from_text(text)
    return None


def visual_call_from_call_chain(name: str | None) -> str | None:
    if isinstance(name, str) and name in VISUAL_CALLS:
        return name
    return None
