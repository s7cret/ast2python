from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from ast2python.lowering_matrix.schema import LoweringMatrixEntry

LOWERING_MATRIX_RESOURCE = "lowering_matrix.json"
SOURCE_MAP_CONTRACT_RESOURCE = "source_map_contract.json"


def _resource_path(name: str) -> Path:
    return Path(str(files("ast2python.lowering_matrix").joinpath(name)))


def load_lowering_matrix(path: str | Path | None = None) -> dict[str, Any]:
    matrix_path = Path(path) if path is not None else _resource_path(LOWERING_MATRIX_RESOURCE)
    return cast(dict[str, Any], json.loads(matrix_path.read_text(encoding="utf-8")))


def load_lowering_entries(path: str | Path | None = None) -> list[LoweringMatrixEntry]:
    payload = load_lowering_matrix(path)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("lowering matrix entries must be an array")
    return [LoweringMatrixEntry.from_dict(item) for item in entries]


def load_source_map_contract(path: str | Path | None = None) -> dict[str, Any]:
    contract_path = Path(path) if path is not None else _resource_path(SOURCE_MAP_CONTRACT_RESOURCE)
    return cast(dict[str, Any], json.loads(contract_path.read_text(encoding="utf-8")))
