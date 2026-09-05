"""Dependency-sliced child methods from checked IR, not Pine string replacement."""

import ast

import pytest

from ast2python.errors import BundleInvariantError
from tests.test_rc6_input_metadata import compile_source


@pytest.mark.parametrize("version", range(1, 7))
def test_request_child_method_all_versions(version):
    decl, fn = ("indicator", "request.security") if version >= 5 else ("study", "security")
    result = compile_source(f'//@version={version}\n{decl}("child")\nx={fn}("EX:S","5",close)\n')
    methods = [
        n
        for n in ast.walk(ast.parse(result.emitted.code))
        if isinstance(n, ast.FunctionDef) and n.name.startswith("request_")
    ]
    assert len(methods) == 1
    assert "_PineLibRequestExpression" in result.emitted.code
    assert "pl_close_v1_" in ast.unparse(methods[0]) and "tx=self.runtime" in ast.unparse(
        methods[0]
    )


@pytest.mark.parametrize(
    "body",
    [
        'f(x)=>x+1\ny=request.security("EX:S","5",f(close))',
        'x=request.security("EX:S","5",strategy.equity)',
    ],
)
def test_unsupported_child_dependencies_fail_without_parent_substitution(body):
    with pytest.raises((BundleInvariantError, ValueError)):
        compile_source('//@version=6\nstrategy("unsupported")\n' + body + "\n")


@pytest.mark.parametrize(
    "version,enabled,success",
    [(5, None, False), (5, True, True), (6, None, True), (6, False, False)],
)
def test_dynamic_declaration_controls_contexts(version, enabled, success):
    option = "" if enabled is None else ",dynamic_requests=" + str(enabled).lower()
    source = f'//@version={version}\nindicator("dynamic"{option})\nx=close>0 ? "EX:S" : "EX:T"\ny=request.security(x,"5",close)\n'
    if success:
        assert compile_source(source).emitted.code
    else:
        with pytest.raises((BundleInvariantError, ValueError)):
            compile_source(source)


def test_na_broker_field_and_lower_array_have_bindings():
    result = compile_source(
        '//@version=6\nstrategy("types")\na=na(strategy.position_avg_price)\n[x,y]=request.security_lower_tf("EX:S","1",[close,open])\nz=array.get(x,0)\n'
    )
    assert "na_v1" in result.emitted.code
    assert "get_v1" in result.emitted.code


@pytest.mark.parametrize("version,enabled", [(5, True), (6, None)])
def test_nested_child_methods_preserve_independent_context_calls(version, enabled):
    option = "" if enabled is None else ",dynamic_requests=true"
    result = compile_source(
        f'//@version={version}\nindicator("nested"{option})\nx=request.security("EX:S","5",request.security("","",close))\n'
    )
    methods = [
        node
        for node in ast.walk(ast.parse(result.emitted.code))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("request_")
    ]
    assert len(methods) == 2
    assert all("self.runtime" in ast.unparse(method) for method in methods)


def test_nested_requests_disabled_still_fail_explicitly():
    with pytest.raises(BundleInvariantError, match="dynamic_requests"):
        compile_source(
            '//@version=6\nindicator("disabled",dynamic_requests=false)\nx=request.security("EX:S","5",request.security("EX:S","1",close))\n'
        )
