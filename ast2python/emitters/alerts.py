"""Pine alert call and statement emitters."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ast2python.ast.schema import ASTNode


class PineAlertEmitter:
    """Lower Pine alert APIs through the owning translator."""

    def __init__(self, translator: Any) -> None:
        self.translator = translator

    def emit_alert_condition_statement(self, node: ASTNode) -> None:
        translator = self.translator
        args = []
        condition = node.child("condition") or node.child("expression")
        if condition is not None:
            args.append(translator.translate_expression(condition))
        title = node.child("title")
        message = node.child("message")
        kwargs = []
        if title is not None:
            kwargs.append(f"title={translator.translate_expression(title)}")
        if message is not None:
            kwargs.append(f"message={translator.translate_expression(message)}")
        translator.ctx.coverage.builtin("alertcondition")
        translator.emitter.line(
            f"self._record_alert('alertcondition'{', ' if args or kwargs else ''}{', '.join(args + kwargs)}, source_map=\"{node.loc.source_map if node.loc else ''}\")",  # noqa: E501
            loc=node.loc,
            source=node.source,
        )

    def translate_alert_call(self, name: str, node: ASTNode) -> str:
        translator = self.translator
        args: list[str] = []
        kwargs: list[str] = []
        for arg_name, arg in translator._call_arguments(node):
            rendered = translator.translate_expression(arg)
            if arg_name is None:
                args.append(rendered)
            else:
                kwargs.append(f"{arg_name}={rendered}")
        translator.ctx.coverage.builtin(name)
        return f'self._record_alert({name!r}{", " if args or kwargs else ""}{", ".join(args + kwargs)}, source_map="{node.loc.source_map if node.loc else ""}")'  # noqa: E501
