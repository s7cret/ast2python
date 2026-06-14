"""Translation metadata payload construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.diagnostics import Severity
from ast2python.templates.module import class_name_for_mode
from ast2python.unsupported import node_kind_counts, unsupported_node_catalog
from ast2python.version import RUNTIME_CONTRACT_VERSION
from ast2python.version import __version__ as ast2python_version

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTProgram


def build_metadata(
    translator: Any, program: ASTProgram, *, title: str, module_name: str
) -> dict[str, Any]:
    declaration = {
        "kind": translator.ctx.mode,
        "title": title,
        "arguments": translator.ctx.strategy_metadata,
    }
    return {
        "ast2python_version": ast2python_version,
        "generator_milestone": f"v{ast2python_version}",
        "target_runtime_contract": RUNTIME_CONTRACT_VERSION,
        "pine_version": program.field("version", "language_version", default=6),
        "source_file": f"{module_name}.pine",
        "module_name": module_name,
        "compile_profile": translator.compile_profile,
        "visual_policy": translator.visual_policy,
        "class_name": class_name_for_mode(translator.ctx.mode),
        "declaration": declaration,
        "inputs": translator.ctx.input_metadata,
        "types": translator.ctx.type_metadata,
        "used_builtins": sorted(translator.ctx.coverage.builtins),
        "node_kind_counts": node_kind_counts(program),
        "unsupported_nodes": unsupported_node_catalog(program),
        "import_aliases": sorted(
            translator.ctx.import_aliases.values(), key=lambda item: item["alias"]
        ),
        "unsupported_declaration_args": sorted(set(translator.ctx.unsupported_declaration_args)),
        "unsafe": translator.compile_profile != "production" or not translator.parity_safe,
        "parity_safe": translator.parity_safe,
        "codegen_safe": not any(d.severity is Severity.ERROR for d in translator.ctx.diagnostics),
        "runtime_contract_safe": translator.parity_safe,
        "unsupported_features": sorted(translator.unsupported_features),
        "parity_risks": translator.parity_risks,
        "producer_metadata": program.field("producer_metadata"),
        "diagnostics": [item.to_dict() for item in translator.ctx.diagnostics],
        "source_map_file": f"{module_name}.sourcemap.json",
    }
