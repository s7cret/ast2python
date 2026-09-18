"""Stage 2.4 reference identity through the exact generated execution path."""
import pytest

from pinelib.state.checkpoint import from_portable
from tests.test_rc6_input_metadata import compile_source, run_source


def source(body: str, version: int = 6) -> str:
    return f'//@version={version}\nindicator("stage24")\n{body}\n'


def trace(body: str, version: int = 6, closes=(1, 2, 3)):
    runtime, _, _ = run_source(source(body, version), closes=closes)
    return [from_portable(event.payload["series"]) for event in runtime.visuals.committed]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "f(array<int> x)=>x\na=array.new<int>(1,1)\nb=f(a)\n"
            "array.set(b,0,7)\nplot(array.get(a,0))",
            [7, 7, 7],
        ),
        (
            'f(map<string,int> x)=>x\nm=map.new<string,int>()\nmap.put(m,"x",1)\n'
            'n=f(m)\nmap.put(n,"x",7)\nplot(map.get(m,"x"))',
            [7, 7, 7],
        ),
        (
            "f(matrix<int> x)=>x\nm=matrix.new<int>(1,1,1)\nn=f(m)\n"
            "matrix.set(n,0,0,7)\nplot(matrix.get(m,0,0))",
            [7, 7, 7],
        ),
    ],
)
def test_udf_parameter_and_return_preserve_reference_identity(version, body, expected):
    assert trace(body, version) == expected


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "f(array<int> x)=>array.copy(x)\na=array.new<int>(1,1)\nb=f(a)\n"
            "array.set(b,0,7)\nplot(array.get(a,0))\nplot(array.get(b,0))",
            [1, 7] * 3,
        ),
        (
            'm=map.new<string,int>()\nmap.put(m,"x",1)\nn=map.copy(m)\n'
            'map.put(n,"x",7)\nplot(map.get(m,"x"))\nplot(map.get(n,"x"))',
            [1, 7] * 3,
        ),
        (
            "m=matrix.new<int>(1,1,1)\nn=matrix.copy(m)\nmatrix.set(n,0,0,7)\n"
            "plot(matrix.get(m,0,0))\nplot(matrix.get(n,0,0))",
            [1, 7] * 3,
        ),
    ],
)
def test_generated_copy_has_independent_outer_identity(version, body, expected):
    assert trace(body, version) == expected


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "a=array.new<int>(1,int(close))\np=a[1]\nplot(na(p) ? 0 : array.get(p,0))",
        'm=map.new<string,int>()\nmap.put(m,"x",int(close))\np=m[1]\n'
        'plot(na(p) ? 0 : map.get(p,"x"))',
        "m=matrix.new<int>(1,1,int(close))\np=m[1]\n"
        "plot(na(p) ? 0 : matrix.get(p,0,0))",
    ],
)
def test_generated_collection_history_is_previous_reference_instance(version, body):
    assert trace(body, version) == [0, 1, 2]


def test_v4_array_reference_history_stays_fail_closed():
    with pytest.raises(ValueError, match="production-blocking diagnostics"):
        compile_source(
            '//@version=4\nstudy("stage24")\na=array.new_int(1,1)\np=a[1]\n'
        )

@pytest.mark.parametrize(
    "body",
    [
        "a=array.new<bool>(1)\nplot(array.get(a,0) == false ? 1 : 0)",
        "m=matrix.new<bool>(1,1)\nplot(matrix.get(m,0,0) == false ? 1 : 0)",
    ],
)
def test_generated_v6_omitted_bool_collection_initial_is_not_na(body):
    assert trace(body, 6) == [1, 1, 1]


@pytest.mark.parametrize(
    "body",
    [
        "a=array.new<bool>(1)\nplot(array.get(a,0) == false ? 1 : 0)",
        "m=matrix.new<bool>(1,1)\nplot(matrix.get(m,0,0) == false ? 1 : 0)",
    ],
)
def test_generated_v5_omitted_bool_collection_initial_keeps_legacy_na(body):
    assert trace(body, 5) == [0, 0, 0]
