from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

CONFLICT_ALIASES = {
    "abs": "pine_abs",
    "round": "pine_round",
    "min": "pine_min",
    "max": "pine_max",
    "sum": "pine_sum",
    "input": "pine_input",
    "str": "pine_str",
}


@dataclass
class ImportManager:
    from_imports: dict[str, dict[str, str | None]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    plain_imports: dict[str, str | None] = field(default_factory=dict)

    def require_from(self, module: str, symbol: str, alias: str | None = None) -> str:
        resolved_alias = alias or CONFLICT_ALIASES.get(symbol)
        self.from_imports[module][symbol] = resolved_alias
        return resolved_alias or symbol

    def require_import(self, module: str, alias: str | None = None) -> str:
        self.plain_imports[module] = alias
        return alias or module

    def render(self) -> list[str]:
        lines: list[str] = []
        for module in sorted(self.plain_imports):
            alias = self.plain_imports[module]
            lines.append(f"import {module}" if alias is None else f"import {module} as {alias}")
        for module in sorted(self.from_imports):
            pieces: list[str] = []
            for symbol in sorted(self.from_imports[module]):
                alias = self.from_imports[module][symbol]
                pieces.append(symbol if alias is None else f"{symbol} as {alias}")
            lines.append(f"from {module} import {', '.join(pieces)}")
        return lines
