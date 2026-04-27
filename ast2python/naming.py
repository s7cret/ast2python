from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import dataclass, field

from ast2python.errors import NameCollisionError

_CAMEL_BOUNDARY = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_TRAILING = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^0-9A-Za-z_]+")
_UNDERSCORE_RUN = re.compile(r"_+")


def snake_case(value: str) -> str:
    interim = _CAMEL_BOUNDARY.sub(r"\1_\2", value)
    interim = _CAMEL_TRAILING.sub(r"\1_\2", interim)
    interim = _NON_WORD.sub("_", interim)
    interim = _UNDERSCORE_RUN.sub("_", interim).strip("_")
    interim = interim.lower() or "value"
    if interim[0].isdigit():
        interim = f"n_{interim}"
    return interim


def escape_python_name(value: str) -> str:
    if keyword.iskeyword(value) or value in dir(builtins):
        return f"{value}_"
    return value


@dataclass
class NamingRegistry:
    used: set[str] = field(default_factory=set)
    discard_counter: int = 0

    def reserve(self, pine_name: str, *, prefer: str | None = None) -> str:
        base = escape_python_name(prefer or snake_case(pine_name))
        candidate = base
        ordinal = 1
        while candidate in self.used:
            ordinal += 1
            candidate = f"{base}_{ordinal}"
            if ordinal > 10000:
                raise NameCollisionError(f"Unable to allocate unique name for {pine_name!r}")
        self.used.add(candidate)
        return candidate

    def discard_name(self) -> str:
        self.discard_counter += 1
        name = f"_discard_{self.discard_counter}"
        self.used.add(name)
        return name

    def reset_discards(self) -> None:
        self.discard_counter = 0
