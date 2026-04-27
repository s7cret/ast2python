from __future__ import annotations

from collections import Counter
from typing import Any

from ast2python.ast.schema import ASTProgram

SUPPORTED_NODE_KINDS = {
    "Program",
    "DeclarationStatement",
    "VERSION",
    "Block",
    "Argument",
    "Identifier",
    "Literal",
    "TypeRef",
    "Parameter",
    "Field",
    "EnumValue",
    "VarDeclaration",
    "TupleDeclaration",
    "Reassignment",
    "ExpressionStatement",
    "IfStructure",
    "SwitchStructure",
    "SwitchStatement",
    "SwitchCase",
    "ForRangeStructure",
    "ForStructure",
    "WhileStructure",
    "WhileStatement",
    "BreakStatement",
    "ContinueStatement",
    "FunctionDeclaration",
    "FunctionDecl",
    "FunctionDefinition",
    "MethodDeclaration",
    "MethodDecl",
    "TypeDeclaration",
    "UserTypeDeclaration",
    "UDTDeclaration",
    "EnumDeclaration",
    "EnumDecl",
    "BinaryExpr",
    "UnaryExpr",
    "ConditionalExpr",
    "IfExpression",
    "SwitchExpression",
    "CallExpr",
    "MemberAccessExpr",
    "HistoryRefExpr",
    "HistoryReference",
    "SubscriptExpr",
    "IndexExpr",
    "TupleExpr",
}

UNSUPPORTED_DIAGNOSTIC_CATALOG: dict[str, str] = {
    "ImportStatement": "Pine imports are recorded by Pine2AST but external library lowering is not implemented in v0.6.0.",
    "ForInStructure": "for-in loops need collection iterator runtime support before deterministic lowering.",
    "ArrayLiteral": "array literals are not lowered yet; use array.new/copy runtime calls where supported.",
    "MapLiteral": "map literals are not lowered yet.",
    "MatrixLiteral": "matrix literals are not lowered yet.",
    "AlertCondition": "alertcondition integration is not emitted yet.",
}


def unsupported_node_catalog(program: ASTProgram) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter(node.kind for node in program.descendants() if node.kind not in SUPPORTED_NODE_KINDS)
    return [
        {
            "kind": kind,
            "count": count,
            "reason": UNSUPPORTED_DIAGNOSTIC_CATALOG.get(kind, "No v0.6.0 lowering rule is registered for this Pine2AST node kind."),
        }
        for kind, count in sorted(counts.items())
    ]


def node_kind_counts(program: ASTProgram) -> dict[str, int]:
    return dict(sorted(Counter(node.kind for node in program.descendants()).items()))
