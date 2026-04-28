from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ast2python.lowering_matrix.loader import load_lowering_entries, load_source_map_contract


def lowering_matrix_markdown() -> str:
    entries = load_lowering_entries()
    by_category: dict[str, list] = defaultdict(list)
    for entry in entries:
        by_category[entry.category].append(entry)

    lines = [
        "# AST2Python Lowering Matrix",
        "",
        "Scope: amended 6-package Pain Stack P0 lowering/source-map matrix for runtime "
        "contract `1.4`.",
        "This is a verified-subset matrix, not a full Pine v6 or full TradingView "
        "compatibility claim.",
        "",
    ]
    for category in sorted(by_category):
        lines.extend([f"## {category}", ""])
        lines.append("| AST kind / builtin | Priority | Lowering | Source map | Coverage | Owner |")
        lines.append("|---|---|---|---|---|---|")
        for entry in sorted(by_category[category], key=lambda item: item.ast_kind):
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{entry.ast_kind}`",
                        entry.priority,
                        entry.lowering_status,
                        entry.source_map_status,
                        entry.coverage_status,
                        f"`{entry.owner_method}`",
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def source_map_contract_markdown() -> str:
    contract = load_source_map_contract()
    lines = [
        "# AST2Python Source Map Contract",
        "",
        f"Runtime contract: `{contract['runtime_contract']}`",
        f"Artifact: `{contract['artifact']}`",
        f"Format: `{contract['format']}`",
        "",
        "## Required fields",
        "",
    ]
    lines.extend(f"- `{field}`" for field in contract["required_fields"])
    lines.extend(["", "## Guarantees", ""])
    lines.extend(f"- {item}" for item in contract["guarantees"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in contract["limitations"])
    return "\n".join(lines).rstrip() + "\n"


def export_lowering_matrix_markdown(path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(lowering_matrix_markdown(), encoding="utf-8")
    return out


def export_source_map_contract_markdown(path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(source_map_contract_markdown(), encoding="utf-8")
    return out
