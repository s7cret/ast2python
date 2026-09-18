"""S2-01..10 regressions with literal/math-derived expectations, never snapshots.

Authority: TradingView operators, type-system, strings, colors, arrays and enums.
"""

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib.state.checkpoint import from_portable

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)
from tests.test_nominal_language_execution import source
from tests.test_rc6_input_metadata import compile_source, run_source


def trace(body, version=6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(source(body, version), closes=closes)
    return [from_portable(e.payload["series"]) for e in runtime.visuals.committed]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expr,expected",
    [("5%2", 1), ("-5%2", 1), ("5%-2", -1), ("-5%-2", -1), ("-5.5%2.0", 0.5), ("5.5%-2.0", -0.5)],
)
def test_modulo_default_and_runtime_have_one_floor_contract(version, expr, expected):
    kind = "float" if "." in expr else "int"
    assert (
        trace(f"n=input.{kind}({expr})\nplot(n)\nplot({expr})", version) == [expected, expected] * 3
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expr,expected",
    [("false==0", False), ("true==1", False), ("false!=0", True), ("true!=1", True)],
)
def test_bool_number_equality_is_not_python_equality(version, expr, expected):
    out = trace(f"n=input.bool({expr})\nplot(n)\nplot({expr})", version)
    assert all(type(x) is bool and x is expected for x in out)


@pytest.mark.parametrize("number", [2**53 - 1, 2**53 + 1, 2**63 - 1, -(2**53 + 1), -(2**63) + 1])
@pytest.mark.parametrize("divisor", [1, -1, 3, -3])
def test_legacy_int_division_does_not_round_through_float(number, divisor):
    q = abs(number) // abs(divisor)
    expected = -q if (number < 0) != (divisor < 0) else q
    assert (
        trace(
            f"n=input.int({number}/{divisor})\nplot(n=={expected})\nplot(({number}/{divisor})=={expected})",
            5,
        )
        == [True, True] * 3
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">", ">="])
@pytest.mark.parametrize("operands", [("close", "na"), ("na", "close")])
def test_literal_na_comparison_is_rejected(version, op, operands):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(f"plot({operands[0]}{op}{operands[1]})", version))


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("default", ["1+2", "f()", "a", "close+1"])
def test_udt_default_is_not_an_arbitrary_expression(version, default):
    with pytest.raises(ConsumerBundleError):
        compile_source(
            source(f"a=2\nf()=>3\ntype P\n    float x={default}\np=P.new()\nplot(p.x)", version)
        )


@pytest.mark.parametrize("version", [5, 6])
def test_udt_permitted_defaults_remain_usable(version):
    assert trace(
        "type P\n    int x=-3\n    float y=close\np=P.new()\nplot(p.x)\nplot(p.y)", version
    ) == [-3, 1, -3, 2, -3, 3]


@pytest.mark.parametrize("version", [5, 6])
def test_string_named_parameters_and_defaults(version):
    body = (
        'plot(str.contains(str="b",source="abc"))\n'
        'plot(str.startswith(source="abc",str="ab"))\n'
        'plot(str.endswith(source="abc",str="bc"))\n'
        'plot(str.substring("abc",begin_pos=1)=="bc")\n'
        'plot(str.substring("abcd",end_pos=3,begin_pos=1)=="bc")\n'
        'plot(str.replace("aba","a","x")=="xba")\n'
        'plot(str.replace("aba","a","x",occurrence=1)=="abx")\n'
        'plot(str.replace_all("aba","a","x")=="xbx")\n'
        'xs=str.split("a,b",",")\nplot(array.get(xs,0)=="a")\nplot(array.get(xs,1)=="b")'
    )
    assert trace(body, version, closes=(1,)) == [True] * 10


@pytest.mark.parametrize("version", [5, 6])
def test_nz_distinguishes_omission_explicit_na_and_types(version):
    body = (
        "int x=na\nfloat y=na\ncolor c=na\n"
        "plot(nz(x))\nplot(nz(y))\nplot(na(nz(x,int(na))))\n"
        "plot(nz(x,7))\nplot(color.t(nz(c)))"
    )
    out = trace(body, version, closes=(1,))
    assert out == [0, 0.0, True, 7, 100.0]
    assert type(out[0]) is int and type(out[1]) is float


@pytest.mark.parametrize("version,red", [(5, 255.0), (6, 242.0)])
def test_color_components_and_versioned_palette(version, red):
    assert trace(
        "plot(color.r(color.red))\nplot(color.g(#123456))\nplot(color.b(#123456))\nplot(color.t(#12345600))",
        version,
        closes=(1,),
    ) == [red, 52.0, 86.0, 100.0]


@pytest.mark.parametrize("version", [5, 6])
def test_array_from_sum_slices_and_na(version):
    body = (
        "a=array.from(1,2,3)\nplot(array.sum(a))\nplot(a.sum())\n"
        "s=array.slice(a,1,3)\nplot(array.sum(s))\n"
        "array.set(a,1,9)\nplot(array.sum(s))\n"
        "b=array.new<float>(3)\narray.set(b,1,2.5)\nplot(array.sum(b))\n"
        "c=array.new<int>()\nplot(na(array.sum(c)))"
    )
    assert trace(body, version, closes=(1,)) == [6, 6, 5, 12, 2.5, True]


@pytest.mark.parametrize("version", [5, 6])
def test_enum_title_and_default_title(version):
    body = (
        'enum E\n    one="First"\n    two\n'
        'plot(str.tostring(E.one)=="First")\nplot(str.tostring(E.two)=="two")'
    )
    assert trace(body, version) == [True, True] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_imported_same_named_enum_titles_are_distinct(version):
    libs = {
        "u/A/1": library('export enum E\n    one="Alpha"', "A", version),
        "u/B/1": library('export enum E\n    one="Beta"', "B", version),
    }
    compiled, _ = compile_linked(
        script(
            'plot(str.tostring(a.E.one)=="Alpha")\nplot(str.tostring(b.E.one)=="Beta")',
            "import u/A/1 as a\nimport u/B/1 as b",
            version,
        ),
        libs,
    )
    r, cls = runtime_for(compiled)
    assert advance(r, cls, [1, 2]) == [True, True] * 2


@pytest.mark.parametrize(
    "body",
    [
        'plot(str.contains("a",1))',
        'plot(str.substring("abc","1"))',
        'plot(str.replace("a","a"))',
        'plot(nz("bad"))',
        'enum E\n    a\nplot(str.tostring(E.a,"#.0"))',
        "type P\n    int n\np=P.new()\nplot(str.tostring(p))",
        'a=array.from(1,"bad")\nplot(array.size(a))',
        'a=array.from("a","b")\nplot(array.sum(a))',
    ],
)
def test_new_bindings_do_not_widen_invalid_argument_domain(body):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(body))
