from __future__ import annotations

AST_CONTRACT_VERSION = "pine.ast_contract.v1"
OPENPINE_FRONTEND_CONTRACT_VERSION = "openpine.frontend.v1"
RUNTIME_CONTRACT_VERSION = "1.4"
RUNTIME_CONTRACT_ALIASES = frozenset(
    {RUNTIME_CONTRACT_VERSION, "v1.4", "runtime_contract_v1_4", "runtime_contract_v1.4"}
)


def runtime_contract_is_compatible(value: object) -> bool:
    return value is None or value in RUNTIME_CONTRACT_ALIASES


def ast_contract_is_current(value: object) -> bool:
    return value == AST_CONTRACT_VERSION
