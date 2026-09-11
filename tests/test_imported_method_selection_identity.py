"""The executed method must be the exact declaration selected with visibility."""

import json

import pytest

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("named", [False, True])
def test_public_method_is_not_rebound_to_private_overload(version, reverse, named):
    rows = [
        "method pick(simple int self,int step)=>self+step+1000",
        "export method pick(simple int self,float step)=>self+step+100",
    ]
    if reverse:
        rows.reverse()
    argument = "step=1" if named else "1"
    compiled, _ = compile_linked(
        script(f"n=2\nplot(n.pick({argument}))", version=version),
        {"user/Lib/1": library("\n".join(rows), version=version)},
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [10, 20, 30]) == [103, 103, 103]


@pytest.mark.parametrize("version", [5, 6])
def test_internal_private_and_external_public_overloads_keep_separate_state_on_restore(version):
    body = (
        "method count(simple int self,int step)=>\n"
        "    var int n=1000\n    n+=step\n    n\n"
        "export method count(simple int self,float step)=>\n"
        "    var float n=100\n    n+=step\n    n\n"
        "export method inside(simple int self)=>self.count(1)"
    )
    compiled, _ = compile_linked(
        script("n=2\nplot(n.count(1))\nplot(n.inside())", version=version),
        {"user/Lib/1": library(body, version=version)},
    )
    whole, cls = runtime_for(compiled)
    expected = [101, 1001, 102, 1002, 103, 1003]
    assert advance(whole, cls, [10, 20, 30]) == expected
    split, _ = runtime_for(compiled)
    advance(split, cls, [10])
    snapshot = json.loads(json.dumps(split.checkpoint().to_dict()))
    resumed, _ = runtime_for(compiled)
    resumed.restore(snapshot)
    assert advance(resumed, cls, [20, 30], start=1) == expected
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()
