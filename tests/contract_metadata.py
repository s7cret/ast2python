from __future__ import annotations

from copy import deepcopy
from typing import Any

VALID_PRODUCER_METADATA: dict[str, Any] = {
    "contract": "pine.ast_contract.v1",
    "producer": {"name": "pine2ast", "version": "test-fixture"},
    "schema_version": "1.0",
    "pine_language_version": 6,
    "runtime_contract_profile": "v1.4",
    "runtime_contract": "runtime_contract_v1_4",
    "parser_gate": "pass",
    "semantic_gate": "pass",
}


def with_valid_producer_metadata(program: Any) -> dict[str, Any]:
    """Return a fixture Program with valid Pine2AST runtime-contract metadata.

    Tests use this only for ASTs intended to model accepted Pine2AST output.
    Negative contract tests still construct missing/mismatched metadata directly.
    """
    raw = program.raw if hasattr(program, "raw") else program
    result = deepcopy(raw)
    metadata = result.get("producer_metadata")
    if not isinstance(metadata, dict):
        result["producer_metadata"] = deepcopy(VALID_PRODUCER_METADATA)
        return result
    patched = deepcopy(VALID_PRODUCER_METADATA)
    patched.update(metadata)
    if not patched.get("runtime_contract"):
        patched["runtime_contract"] = VALID_PRODUCER_METADATA["runtime_contract"]
    if not patched.get("runtime_contract_profile"):
        patched["runtime_contract_profile"] = VALID_PRODUCER_METADATA["runtime_contract_profile"]
    result["producer_metadata"] = patched
    return result
