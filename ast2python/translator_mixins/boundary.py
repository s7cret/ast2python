"""Translator mixins: boundary enforcement (contract, realtime, varip)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ast2python.diagnostics import (
    CALC_ON_EVERY_TICK_UNSAFE,
    CONTRACT_VERSION_MISMATCH,
    VARIP_UNSAFE,
    Severity,
)
from ast2python.errors import ValidationError
from ast2python.unsupported import literal_value
from ast2python.version import RUNTIME_CONTRACT_VERSION

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode, ASTProgram


def enforce_frontend_contract(self: Any, program: ASTProgram) -> None:
    """Check Pine2AST producer metadata, contract version, and frontend gates."""
    frontend_diagnostics = [
        item
        for item in program.field("diagnostics", default=[]) or []
        if isinstance(item, dict) and str(item.get("severity", "")).lower() in {"error", "fatal"}
    ]
    if frontend_diagnostics:
        self.ctx.add_diagnostic(
            "P2A_FRONTEND_DIAGNOSTIC_BLOCK",
            "Pine2AST embedded ERROR/FATAL diagnostics block code generation",
            Severity.ERROR,
            details={"frontend_diagnostics": frontend_diagnostics},
        )
        if not self.allow_invalid_ast:
            raise ValidationError("Pine2AST ERROR/FATAL diagnostics block code generation")
        self.parity_safe = False
        self.parity_risks.append("allow_invalid_ast override used with frontend errors")

    metadata = program.field("producer_metadata")
    runtime_contract = None
    contract = None
    if isinstance(metadata, dict):
        contract = metadata.get("contract")
        runtime_contract = metadata.get("runtime_contract") or metadata.get(
            "runtime_contract_profile"
        )
    expected = RUNTIME_CONTRACT_VERSION
    aliases = {expected, "v1.4", "runtime_contract_v1_4", "runtime_contract_v1.4"}
    metadata_contract_ok = (
        isinstance(metadata, dict)
        and contract == "pain.ast_contract.v1"
        and runtime_contract in aliases
    )
    if runtime_contract is not None:
        self.ctx.producer_runtime_contract = runtime_contract
    if not metadata_contract_ok:
        self.ctx.add_diagnostic(
            CONTRACT_VERSION_MISMATCH,
            "Pine2AST producer metadata missing or mismatched contract/runtime profile",
            Severity.ERROR,
            details={
                "expected_contract": "pain.ast_contract.v1",
                "actual_contract": contract,
                "expected_runtime_contract": expected,
                "actual_runtime_contract": runtime_contract,
                "metadata": metadata,
            },
        )
        if not self.allow_contract_mismatch:
            raise ValidationError("Pine2AST producer metadata missing/mismatched runtime contract")
        self.parity_safe = False
        self.parity_risks.append("allow_contract_mismatch override used")

    if metadata_contract_ok:
        unsafe_gates = {
            key: metadata.get(key)
            for key in ("parser_gate", "semantic_gate")
            if metadata.get(key) != "pass"
        }
        if unsafe_gates:
            self.ctx.add_diagnostic(
                "P2A_FRONTEND_GATE_BLOCK",
                "Pine2AST producer metadata gate status is not pass",
                Severity.ERROR,
                details={"gates": unsafe_gates},
            )
            if not self.allow_invalid_ast:
                raise ValidationError("Pine2AST producer metadata gates are not pass")
            self.parity_safe = False
            self.parity_risks.append("allow_invalid_ast override used with non-pass frontend gates")


def enforce_realtime_boundary(self: Any, declaration: ASTNode) -> None:
    """Fail closed if calc_on_every_tick is set without realtime simulation."""
    if self.ctx.mode != "strategy" or not _strategy_calc_on_every_tick_enabled(self, declaration):
        return
    self.ctx.add_diagnostic(
        CALC_ON_EVERY_TICK_UNSAFE,
        "calc_on_every_tick requires TradingView realtime rollback/varip semantics "
        "and is rejected in parity codegen mode",
        Severity.ERROR,
        details={"allow_flag": "allow_realtime_local_simulation"},
    )
    if not self.allow_realtime_local_simulation:
        raise ValidationError("calc_on_every_tick is unsupported in parity codegen mode")
    self.parity_safe = False
    self.unsupported_features.add("realtime_local_simulation")
    self.parity_risks.append(
        "allow_realtime_local_simulation override used; supplied tick mode is local simulation only"
    )


def enforce_varip_boundary(self: Any, program: ASTProgram) -> None:
    """Fail closed if varip is used without realtime simulation."""
    varip_nodes = [
        node
        for node in program.descendants()
        if node.kind == "VarDeclaration" and str(node.field("mode", default="")).lower() == "varip"
    ]
    if not varip_nodes:
        return
    self.ctx.add_diagnostic(
        VARIP_UNSAFE,
        "varip requires TradingView realtime rollback semantics and is rejected in parity codegen mode",
        Severity.ERROR,
        details={"allow_flag": "allow_realtime_local_simulation", "count": len(varip_nodes)},
    )
    if not self.allow_realtime_local_simulation:
        raise ValidationError("varip is unsupported without realtime rollback semantics")
    self.parity_safe = False
    self.unsupported_features.add("varip_local_simulation")
    self.parity_risks.append(
        "allow_realtime_local_simulation override used with varip; state persistence is local simulation only"
    )


def _strategy_calc_on_every_tick_enabled(self: Any, declaration: ASTNode) -> bool:
    """Check if the strategy declaration enables calc_on_every_tick."""
    call = declaration.child("call")
    if call is None:
        return False
    for name, value_node in self._call_arguments(call):
        if name != "calc_on_every_tick":
            continue
        if value_node.kind == "Literal":
            return bool(literal_value(value_node))
        rendered = self.translate_expression(value_node)
        return rendered == "True"
    return False
