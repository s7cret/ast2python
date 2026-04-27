from __future__ import annotations

from typing import Any, Protocol


class GeneratedModule(Protocol):
    def run(self, bars: list[Any]) -> list[Any]: ...
