import pytest

from ast2python.diagnostics import VISUAL_OBJECT_USED_AS_VALUE
from ast2python.errors import TypeResolutionError
from ast2python.translator import translate_ast


def decl():
    return {"kind": "DeclarationStatement", "script_type": "indicator", "call": {"kind": "CallExpr", "callee": {"kind": "Identifier", "name": "indicator"}, "arguments": [{"kind": "Argument", "name": None, "value": {"kind": "Literal", "literal_type": "string", "value": "v04"}}]}}


def lit(value, typ="int"):
    return {"kind": "Literal", "literal_type": typ, "value": value}


def ident(name):
    return {"kind": "Identifier", "name": name}


def arg(value, name=None):
    return {"kind": "Argument", "name": name, "value": value}


def program(items):
    return {"kind": "Program", "language": "pine", "version": 6, "declaration": decl(), "items": items}


def test_v0_4_switch_loop_function_method_udt_enum_compile_snapshot():
    items = [
        {"kind": "TypeDeclaration", "name": "Pivot", "fields": [{"kind": "Field", "name": "price", "type": "float"}, {"kind": "Field", "name": "index", "type": "int"}]},
        {"kind": "EnumDeclaration", "name": "Direction", "values": [{"kind": "EnumValue", "name": "long"}, {"kind": "EnumValue", "name": "short"}]},
        {"kind": "FunctionDeclaration", "name": "addOne", "params": [{"kind": "Parameter", "name": "x", "type_ref": {"kind": "TypeRef", "name": "int"}}], "body": {"kind": "Block", "statements": [{"kind": "ExpressionStatement", "expression": {"kind": "BinaryExpr", "op": "+", "left": ident("x"), "right": lit(1)}}]}},
        {"kind": "MethodDeclaration", "name": "pricePlus", "params": [{"kind": "Parameter", "name": "this", "type_ref": {"kind": "TypeRef", "name": "Pivot"}}, {"kind": "Parameter", "name": "n", "type_ref": {"kind": "TypeRef", "name": "float"}}], "body": {"kind": "Block", "statements": [{"kind": "ExpressionStatement", "expression": {"kind": "BinaryExpr", "op": "+", "left": {"kind": "MemberAccessExpr", "object": ident("this"), "member": "price"}, "right": ident("n")}}]}},
        {"kind": "VarDeclaration", "name": "x", "initializer": lit(0)},
        {"kind": "VarDeclaration", "name": "p", "type_ref": {"kind": "TypeRef", "name": "Pivot"}, "initializer": {"kind": "CallExpr", "callee": ident("Pivot"), "arguments": [arg(lit(1.5, "float"), "price"), arg(lit(7), "index")]}},
        {"kind": "VarDeclaration", "name": "old", "initializer": {"kind": "MemberAccessExpr", "member": "price", "object": {"kind": "HistoryRefExpr", "base": ident("p"), "offset": lit(10)}}},
        {"kind": "VarDeclaration", "name": "meth", "initializer": {"kind": "CallExpr", "callee": {"kind": "MemberAccessExpr", "object": ident("p"), "member": "pricePlus"}, "arguments": [arg(lit(2.0, "float"))]}},
        {"kind": "VarDeclaration", "name": "sw", "initializer": {"kind": "SwitchExpression", "subject": ident("x"), "cases": [{"kind": "SwitchCase", "value": lit(0), "expression": lit(10)}, {"kind": "SwitchCase", "default": True, "expression": lit(20)}]}},
        {"kind": "SwitchStructure", "subject": ident("x"), "cases": [{"kind": "SwitchCase", "value": lit(0), "body": {"kind": "Block", "statements": [{"kind": "Reassignment", "target": ident("x"), "op": ":=", "value": {"kind": "CallExpr", "callee": ident("addOne"), "arguments": [arg(ident("x"))]}}]}}, {"kind": "SwitchCase", "default": True, "body": {"kind": "Block", "statements": []}}]},
        {"kind": "ForRangeStructure", "variable": "i", "start": lit(0), "end": lit(2), "body": {"kind": "Block", "statements": [{"kind": "ContinueStatement"}]}},
        {"kind": "WhileStructure", "condition": {"kind": "BinaryExpr", "op": "<", "left": ident("x"), "right": lit(5)}, "body": {"kind": "Block", "statements": [{"kind": "Reassignment", "target": ident("x"), "op": "+=", "value": lit(1)}, {"kind": "BreakStatement"}]}},
    ]
    result = translate_ast(program(items), module_name="v0_4")
    assert "@dataclass\nclass Pivot:" in result.code
    assert "class Direction(Enum):" in result.code
    assert "def add_one(self, x):" in result.code
    assert "return (x + 1)" in result.code
    assert "def price_plus(self, this, n):" in result.code
    assert "(self.p[10]).price" in result.code
    assert "self.price_plus(self.p.current, 2.0)" in result.code
    assert "for i in pine_range(0, 2):" in result.code
    assert "max_loop_iterations" in result.code
    assert "break" in result.code and "continue" in result.code
    assert result.metadata["generator_milestone"] == "v0.6.0"
    assert "generation_ratio" in result.coverage
    compile(result.code, "v0_4.py", "exec")


def test_v0_4_visual_recorder_storage_methods_and_misuse_diagnostic():
    visual_new = {"kind": "CallExpr", "callee": {"kind": "MemberAccessExpr", "object": ident("line"), "member": "new"}, "arguments": [arg(lit(0)), arg(ident("close")), arg(lit(1)), arg(ident("close"))]}
    ok = program([
        {"kind": "VarDeclaration", "name": "ln", "type_ref": {"kind": "TypeRef", "name": "line"}, "mode": "var", "initializer": visual_new},
        {"kind": "ExpressionStatement", "expression": {"kind": "CallExpr", "callee": {"kind": "MemberAccessExpr", "object": ident("line"), "member": "set_xy1"}, "arguments": [arg(ident("ln")), arg(ident("bar_index")), arg(ident("close"))]}},
        {"kind": "ExpressionStatement", "expression": {"kind": "CallExpr", "callee": {"kind": "Identifier", "name": "plotshape"}, "arguments": [arg({"kind": "BinaryExpr", "op": ">", "left": ident("close"), "right": ident("open")})]}},
    ])
    result = translate_ast(ok, module_name="visual_ok")
    assert "self.rt.visual.line_new" in result.code
    assert "self.ln.set_current(self.rt.visual.line_new" in result.code
    assert "self.rt.visual.line_set_xy1(self.ln.current" in result.code
    assert "self.rt.visual.plotshape" in result.code
    compile(result.code, "visual_ok.py", "exec")

    bad = program([
        {"kind": "VarDeclaration", "name": "ln", "initializer": visual_new},
        {"kind": "VarDeclaration", "name": "bad", "initializer": {"kind": "BinaryExpr", "op": "+", "left": ident("ln"), "right": lit(1)}},
    ])
    with pytest.raises(TypeResolutionError):
        translate_ast(bad, module_name="visual_bad")
