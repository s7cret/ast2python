"""Persistent scalar declarations and reassignments use transactional storage."""

import pytest

from tests.test_rc6_input_metadata import compile_source, run_source


@pytest.mark.parametrize("version", [4, 5, 6])
def test_var_is_initialized_once_and_history_contains_reassignments(version):
    declaration = "study" if version == 4 else "indicator"
    source = (
        f'//@version={version}\n{declaration}("var")\n'
        "var int total=0\ntotal:=total+1\nplot(total)\nplot(total[1])\n"
    )
    runtime, _, _ = run_source(source, closes=[10, 11, 12])
    records = runtime.visuals.committed
    assert [records[i].payload["series"] for i in (0, 2, 4)] == [1, 2, 3]
    assert [records[i].payload["series"] for i in (3, 5)] == [1, 2]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_ordinary_reassignment_updates_history_even_in_nested_block(version):
    declaration = "study" if version < 5 else "indicator"
    source = (
        f'//@version={version}\n{declaration}("write")\n'
        "x=close\nif close>0\n    x:=close+10\nplot(x[1])\n"
    )
    runtime, _, _ = run_source(source, closes=[10, 20, 30])
    assert [row.payload["series"] for row in runtime.visuals.committed][1:] == [20, 30]


def test_var_initializer_is_not_evaluated_again():
    runtime, _, _ = run_source(
        '//@version=6\nindicator("lazy")\nvar first=close\nplot(first)\n', closes=[1, 8, 9]
    )
    assert [row.payload["series"] for row in runtime.visuals.committed] == [1, 1, 1]


def test_local_var_fails_closed_until_callsite_identity_is_supported():
    with pytest.raises(Exception, match="persistent declarations"):
        compile_source(
            '//@version=6\nindicator("scope")\nif close>0\n    var int x=0\n    x:=x+1\n'
        )


def test_shadowed_global_does_not_silently_alias_storage():
    with pytest.raises(Exception, match="shadowed global"):
        compile_source(
            '//@version=6\nindicator("shadow")\nx=1\nif close>0\n    x=2\n    x:=3\nplot(x)\n'
        )
