from __future__ import annotations

__all__ = [
    "LoweringMatrixEntry",
    "LoweringMatrixError",
    "export_lowering_matrix_markdown",
    "export_source_map_contract_markdown",
    "load_lowering_entries",
    "load_lowering_matrix",
    "load_source_map_contract",
    "lowering_matrix_markdown",
    "source_map_contract_markdown",
    "validate_lowering_matrix",
    "validate_lowering_matrix_payload",
    "validate_source_map_contract",
    "validate_source_map_contract_payload",
]

_EXPORTS = {
    "LoweringMatrixEntry": ("ast2python.lowering_matrix.schema", "LoweringMatrixEntry"),
    "LoweringMatrixError": ("ast2python.lowering_matrix.validate", "LoweringMatrixError"),
    "export_lowering_matrix_markdown": (
        "ast2python.lowering_matrix.export_markdown",
        "export_lowering_matrix_markdown",
    ),
    "export_source_map_contract_markdown": (
        "ast2python.lowering_matrix.export_markdown",
        "export_source_map_contract_markdown",
    ),
    "load_lowering_entries": ("ast2python.lowering_matrix.loader", "load_lowering_entries"),
    "load_lowering_matrix": ("ast2python.lowering_matrix.loader", "load_lowering_matrix"),
    "load_source_map_contract": ("ast2python.lowering_matrix.loader", "load_source_map_contract"),
    "lowering_matrix_markdown": (
        "ast2python.lowering_matrix.export_markdown",
        "lowering_matrix_markdown",
    ),
    "source_map_contract_markdown": (
        "ast2python.lowering_matrix.export_markdown",
        "source_map_contract_markdown",
    ),
    "validate_lowering_matrix": ("ast2python.lowering_matrix.validate", "validate_lowering_matrix"),
    "validate_lowering_matrix_payload": (
        "ast2python.lowering_matrix.validate",
        "validate_lowering_matrix_payload",
    ),
    "validate_source_map_contract": (
        "ast2python.lowering_matrix.validate",
        "validate_source_map_contract",
    ),
    "validate_source_map_contract_payload": (
        "ast2python.lowering_matrix.validate",
        "validate_source_map_contract_payload",
    ),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
