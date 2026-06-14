from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, NoReturn, Protocol

from ast2python.ast.schema import ASTNode, ASTProgram
from ast2python.context import TranslationContext, VariableInfo
from ast2python.emitter import CodeEmitter
from ast2python.emitters.alerts import PineAlertEmitter
from ast2python.emitters.inputs import PineInputEmitter
from ast2python.emitters.time import PineTimeEmitter
from ast2python.result import TranslationResult
from ast2python.types import TypeInfo
from ast2python.visuals import VisualPolicy


class TranslatorMixinProtocol(Protocol):
    """Structural contract used by implementation mixins.

    The concrete ``Translator`` class owns state and composes focused mixins.
    Static checkers need the shared surface explicitly, otherwise each mixin
    looks like an isolated class with no ``ctx``/``emitter``/cross-mixin
    methods.  The explicit attributes below cover the stable public internals;
    ``__getattr__`` keeps experimental private cross-mixin helpers typeable
    without turning every implementation detail into a public protocol method.
    """

    TUPLE_RETURNING_BUILTINS: ClassVar[dict[str, tuple[str, ...]]]

    compile_profile: str
    strict: bool
    emit_source_comments: bool
    allow_invalid_ast: bool
    allow_contract_mismatch: bool
    allow_external_library_stubs: bool
    allow_unsupported_request_stubs: bool
    allow_realtime_local_simulation: bool
    visual_policy: VisualPolicy
    parity_safe: bool
    unsupported_features: set[str]
    parity_risks: list[str]
    ctx: TranslationContext
    emitter: CodeEmitter
    member_chain: Callable[[ASTNode], str | None]
    alert_emitter: PineAlertEmitter
    input_emitter: PineInputEmitter
    time_emitter: PineTimeEmitter
    global_series: list[tuple[VariableInfo, str]]
    input_series: list[tuple[VariableInfo, str, dict[str, Any]]]
    var_flags: list[VariableInfo]
    functions: set[str]
    methods: set[str]
    _temp_series_index: int

    def translate_expression(self, node: ASTNode, *, runtime_expr: str = "self.rt") -> str: ...

    def translate_program(
        self, program: ASTProgram | dict[str, Any], *, module_name: str | None = None
    ) -> TranslationResult: ...

    def _infer_type_info(self, node: ASTNode | None) -> TypeInfo: ...

    def _call_arguments(self, node: ASTNode) -> list[tuple[str | None, ASTNode]]: ...

    def _ordered_call_arguments(
        self, name: str, node: ASTNode
    ) -> list[tuple[str | None, ASTNode]]: ...

    def _is_input_call(self, node: ASTNode) -> bool: ...

    def _is_visual_method_call(self, name: str) -> bool: ...

    def _type_ref_name(self, node: ASTNode) -> str | None: ...

    def _extract_declaration_title(self, declaration: ASTNode) -> str: ...

    def _translate_call(self, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _infer_dtype(self, node: ASTNode | None) -> str: ...

    def _lower_binary_operator(self, op: str, left: str, right: str, node: ASTNode) -> str: ...

    def _reject_visual_value(self, node: ASTNode | None) -> None: ...

    def _collect_globals(self, program: ASTProgram) -> None: ...

    def _emit_type_declarations(self, program: ASTProgram) -> None: ...

    def _emit_function_declarations(self, program: ASTProgram) -> None: ...

    def _strategy_context_kwargs(self, declaration: ASTNode) -> list[tuple[str, str]]: ...

    def _emit_statement(self, node: ASTNode) -> None: ...

    def _diagnose_request_security_captures(self, expression: ASTNode) -> None: ...

    def _contains_request_call(self, node: ASTNode) -> bool: ...

    def _diagnose_request_security_lower_tf_safety(self, expression: ASTNode) -> None: ...

    def _unsupported(self, node: ASTNode, message: str) -> NoReturn: ...
