from __future__ import annotations

from dataclasses import dataclass

from ast2python.admission.ast_view import StrictASTNode
from ast2python.admission.facts import ResolvedCallView, SemanticFactView
from ast2python.errors import BundleInvariantError


@dataclass(frozen=True, slots=True)
class LoweringRecipe:
    opcode: str
    evaluation: str
    effect: str


_STRUCTURAL_RECIPES: dict[str, LoweringRecipe] = {
    "Program": LoweringRecipe("module.program", "structural", "control"),
    "DeclarationStatement": LoweringRecipe("declaration.script", "structural", "declaration"),
    "Argument": LoweringRecipe("call.argument", "eager", "pure"),
    "Literal": LoweringRecipe("literal.value", "eager", "pure"),
    "Identifier": LoweringRecipe("symbol.read", "eager", "pure"),
    "MemberAccessExpr": LoweringRecipe("symbol.member", "eager", "pure"),
    "TypeRef": LoweringRecipe("type.reference", "structural", "declaration"),
    "VarDeclaration": LoweringRecipe("state.declare", "eager", "state"),
    "Reassignment": LoweringRecipe("state.write", "eager", "state"),
    "ExpressionStatement": LoweringRecipe("statement.expression", "eager", "control"),
    "Block": LoweringRecipe("control.block", "structural", "control"),
    "IfStructure": LoweringRecipe("control.if", "lazy", "control"),
    "ElseIfBranch": LoweringRecipe("control.else_if", "lazy", "control"),
    "SwitchStructure": LoweringRecipe("control.switch", "lazy", "control"),
    "SwitchCase": LoweringRecipe("control.switch_case", "lazy", "control"),
    "WhileStructure": LoweringRecipe("control.while", "lazy", "control"),
    "ForInStructure": LoweringRecipe("control.for_in", "lazy", "control"),
    "BreakStatement": LoweringRecipe("control.break", "eager", "control"),
    "ContinueStatement": LoweringRecipe("control.continue", "eager", "control"),
    "FunctionDeclaration": LoweringRecipe("function.define", "structural", "declaration"),
    "MethodDeclaration": LoweringRecipe("method.define", "structural", "declaration"),
    "Parameter": LoweringRecipe("function.parameter", "structural", "declaration"),
    "TupleExpr": LoweringRecipe("tuple.construct", "eager", "pure"),
    "TupleDeclaration": LoweringRecipe("tuple.declare", "eager", "state"),
    "TupleTarget": LoweringRecipe("tuple.target", "structural", "declaration"),
    "ForInTarget": LoweringRecipe("tuple.target", "structural", "declaration"),
    "HistoryRefExpr": LoweringRecipe("series.history", "eager", "pure"),
    "UnaryExpr": LoweringRecipe("operator.unary", "eager", "pure"),
    "TypeDeclaration": LoweringRecipe("type.define", "structural", "declaration"),
    "FieldDeclaration": LoweringRecipe("type.field", "structural", "declaration"),
    "EnumDeclaration": LoweringRecipe("enum.define", "structural", "declaration"),
    "EnumMember": LoweringRecipe("enum.member", "structural", "declaration"),
    "ImportDeclaration": LoweringRecipe("library.import", "structural", "declaration"),
    "GenericInstantiationExpr": LoweringRecipe("type.instantiate", "eager", "pure"),
}


def _binary_recipe(version: int, op: str) -> LoweringRecipe:
    if op in {"and", "or"}:
        return LoweringRecipe(
            "operator.logical.lazy" if version >= 6 else "operator.logical.eager",
            "lazy" if version >= 6 else "eager",
            "pure",
        )
    if op == "/":
        return LoweringRecipe(
            "operator.div.fractional" if version >= 6 else "operator.div.legacy",
            "eager",
            "pure",
        )
    return LoweringRecipe("operator.binary", "eager", "pure")


def _conditional_recipe(version: int) -> LoweringRecipe:
    return LoweringRecipe(
        "control.conditional.lazy" if version >= 4 else "control.conditional.eager",
        "lazy" if version >= 4 else "eager",
        "control",
    )


def _for_range_recipe(version: int) -> LoweringRecipe:
    return LoweringRecipe(
        "control.for_range.dynamic_end" if version >= 6 else "control.for_range.fixed_end",
        "lazy",
        "control",
    )


def _call_recipe(call: ResolvedCallView) -> LoweringRecipe:
    symbol = call.symbol_id
    if symbol.startswith("user:function:"):
        return LoweringRecipe(
            "function.invoke.stateful" if call.stateful else "function.invoke.pure",
            "eager",
            "state" if call.stateful else "pure",
        )
    if symbol.startswith("pine:function:request."):
        return LoweringRecipe("request.invoke", "lazy", "request")
    if symbol.startswith("pine:function:strategy."):
        return LoweringRecipe("strategy.intent", "eager", "strategy")
    if any(
        marker in symbol
        for marker in (
            ":plot",
            ":hline",
            ":fill",
            ":bgcolor",
            ":barcolor",
            ":line.",
            ":label.",
            ":box.",
            ":table.",
        )
    ):
        return LoweringRecipe("visual.invoke", "eager", "visual")
    if any(
        symbol.startswith(prefix)
        for prefix in ("pine:function:array.", "pine:function:map.", "pine:function:matrix.")
    ):
        return LoweringRecipe("collection.invoke", "eager", "state")
    return LoweringRecipe(
        "builtin.invoke.stateful" if call.stateful else "builtin.invoke.pure",
        "eager",
        "state" if call.stateful else "pure",
    )


def select_recipe(
    *,
    version: int,
    node: StrictASTNode,
    fact: SemanticFactView,
    call: ResolvedCallView | None,
) -> LoweringRecipe:
    if node.kind == "CallExpr":
        if call is None:
            raise BundleInvariantError(
                "A2P_RECIPE_CALL_FACT", "CallExpr is missing resolved call identity"
            )
        return _call_recipe(call)
    if node.kind == "BinaryExpr":
        op = fact.raw.get("operator") or node.fields.get("op")
        if not isinstance(op, str) or not op:
            raise BundleInvariantError(
                "A2P_RECIPE_OPERATOR", "BinaryExpr is missing exact operator"
            )
        return _binary_recipe(version, op)
    if node.kind == "ConditionalExpr":
        return _conditional_recipe(version)
    if node.kind == "ForRangeStructure":
        return _for_range_recipe(version)
    recipe = _STRUCTURAL_RECIPES.get(node.kind)
    if recipe is None:
        raise BundleInvariantError(
            "A2P_RECIPE_MISSING",
            f"no exact lowering recipe for AST kind {node.kind!r}",
            details={"pine_version": version, "node_id": node.node_id},
        )
    return recipe


def supported_ast_kinds() -> frozenset[str]:
    return frozenset(_STRUCTURAL_RECIPES) | frozenset(
        {"CallExpr", "BinaryExpr", "ConditionalExpr", "ForRangeStructure"}
    )
