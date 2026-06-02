from __future__ import annotations

from typing import Protocol, TypeAlias

from ast2python.ast.schema import ASTNode
from ast2python.context import TranslationContext

CallNode: TypeAlias = ASTNode
CalleeNode: TypeAlias = ASTNode
CallArguments: TypeAlias = list[tuple[str | None, ASTNode]]


class TimeCallEmitter(Protocol):
    def translate_timestamp_call(self, node: ASTNode) -> str: ...

    def translate_date_helper_call(
        self, name: str, node: ASTNode, *, runtime_expr: str
    ) -> str: ...

    def translate_time_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...


class CallTranslator(Protocol):
    ctx: TranslationContext
    functions: set[str]
    methods: set[str]
    strict: bool

    @property
    def time_emitter(self) -> TimeCallEmitter: ...

    def translate_expression(self, node: ASTNode, *, runtime_expr: str = "self.rt") -> str: ...

    def _call_arguments(self, node: ASTNode) -> CallArguments: ...

    def _translate_alert_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_color_new(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_external_library_call(
        self, name: str, node: ASTNode, *, runtime_expr: str
    ) -> str: ...

    def _translate_input_runtime_lookup(self, node: ASTNode) -> str: ...

    def _translate_math_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_na_helper_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_reference_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_request_security(self, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_request_security_lower_tf(self, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_request_footprint(self, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_strategy_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_str_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_ta_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _translate_unsupported_request_call(
        self, name: str, node: ASTNode, *, runtime_expr: str
    ) -> str: ...

    def _translate_user_func_arg(self, arg: ASTNode, runtime_expr: str) -> str: ...

    def _translate_visual_call(self, name: str, node: ASTNode, *, runtime_expr: str) -> str: ...

    def _is_visual_method_call(self, name: str) -> bool: ...


class ExactCallHandler(Protocol):
    def __call__(
        self, translator: CallTranslator, node: CallNode, *, runtime_expr: str
    ) -> str: ...


class PrefixCallHandler(Protocol):
    def __call__(
        self,
        translator: CallTranslator,
        callee_chain: str,
        node: CallNode,
        *,
        runtime_expr: str,
    ) -> str: ...
