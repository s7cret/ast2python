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
    "FieldDeclaration",
    "EnumValue",
    "EnumMember",
    "TupleTarget",
    "ForInTarget",
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
    "GenericInstantiationExpr",
    "ImportDeclaration",
    "ForInStructure",
    "ArrayLiteral",
    "MapLiteral",
    "AlertCondition",
}

UNSUPPORTED_DIAGNOSTIC_CATALOG: dict[str, str] = {
    "ImportStatement": "legacy Pine import node spelling; use ImportDeclaration for v0.7.0 alias recorder lowering.",  # noqa: E501
    "MatrixLiteral": "matrix literals need shape-preserving lowering; matrix.new calls are supported.",  # noqa: E501
}


def unsupported_node_catalog(program: ASTProgram) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter(
        node.kind for node in program.descendants() if node.kind not in SUPPORTED_NODE_KINDS
    )
    return [
        {
            "kind": kind,
            "count": count,
            "reason": UNSUPPORTED_DIAGNOSTIC_CATALOG.get(
                kind, "No v0.6.0 lowering rule is registered for this Pine2AST node kind."
            ),
        }
        for kind, count in sorted(counts.items())
    ]


def node_kind_counts(program: ASTProgram) -> dict[str, int]:
    return dict(sorted(Counter(node.kind for node in program.descendants()).items()))
