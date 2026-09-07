"""Locked nominal library sources execute through the compiler and real heap."""

import json

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib import CallbackFrame
from pinelib.state.checkpoint import from_portable

from ast2python.artifacts.generated import verify_generated_artifact_v3
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)

TYPES = """export enum Direction
    up="Up"
    down="Down"
export type Counter
    int total=0
    varip int ticks=0
    Direction direction=Direction.up
"""
FUNCTION = """export count(int step)=>
    var Counter c=Counter.new()
    c.total+=step
    c.ticks+=step
    c.direction:=Direction.down
    c
"""


def counters(version=6):
    body = (
        "a=lib.count(1)\nb=lib.count(10)\nc=a.copy()\nc.total+=100\n"
        "plot(a.total)\nplot(b.total)\nplot(a.ticks)\nplot(b.ticks)\n"
        "plot(c.total)\nplot(c.direction==lib.Direction.down)"
    )
    return compile_linked(
        script(body, version=version), {"user/Lib/1": library(TYPES + FUNCTION, version=version)}
    )


@pytest.mark.parametrize("version", [5, 6])
def test_imported_udt_enum_and_local_callsite_state_checkpoint(version):
    compiled, linked = counters(version)
    assert linked.receipt()["profile"] == "same_version_reference_types_v4"
    whole, cls = runtime_for(compiled)
    expected = [1, 10, 1, 10, 101, True, 2, 20, 2, 20, 102, True, 3, 30, 3, 30, 103, True]
    assert advance(whole, cls, [1, 2, 3]) == expected
    split, _ = runtime_for(compiled)
    advance(split, cls, [1])
    resumed, _ = runtime_for(compiled)
    resumed.restore(json.loads(json.dumps(split.checkpoint().to_dict())))
    assert advance(resumed, cls, [2, 3], start=1) == expected
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()
    verify_generated_artifact_v3(
        compiled.artifact.payload,
        emitted=compiled.emitted,
        plan=compiled.plan,
        target=load_pinelib_target_manifest(),
    )


@pytest.mark.parametrize("version", [5, 6])
def test_imported_udt_field_only_varip_rollback_and_continuation(version):
    compiled, _ = counters(version)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1, 10, 1, 10, 101, True]

    def tick(session, sequence, final):
        tx = session.begin(
            CallbackFrame("REALTIME_TICK", sequence, bar_index=1, realtime=True, final_tick=final)
        )
        cls(tx).run()
        values = [from_portable(event.payload["series"]) for event in session.visuals.working[-6:]]
        tx.commit()
        return values

    assert tick(runtime, 1, False) == [2, 20, 2, 20, 102, True]
    assert tick(runtime, 2, False) == [2, 20, 3, 30, 102, True]
    assert tick(runtime, 3, True) == [2, 20, 4, 40, 102, True]
    restored, _ = runtime_for(compiled)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for session in (runtime, restored):
        assert advance(session, cls, [1], start=4)[-6:] == [3, 30, 5, 50, 103, True]
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_two_libraries_keep_same_named_nominal_types_distinct(version):
    libs = {
        "ownerA/Same/1": library(
            "export type Point\n    int n=1\nexport enum Side\n    one",
            name="Same",
            version=version,
        ),
        "ownerB/Same/1": library(
            "export type Point\n    int n=10\nexport enum Side\n    one",
            name="Same",
            version=version,
        ),
    }
    imports = "import ownerA/Same/1 as a\nimport ownerB/Same/1 as b"
    compiled, _ = compile_linked(
        script("p=a.Point.new()\nq=b.Point.new()\nplot(p.n)\nplot(q.n)", imports, version), libs
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1, 10]
    entries = runtime.references.to_json()
    # Runtime representation must contain two separate nominal identities.
    descriptors = {entry["type_descriptor"] for entry in entries["objects"]}
    assert len(descriptors) == 2
    with pytest.raises(ConsumerBundleError):
        compile_linked(script("plot(a.Side.one==b.Side.one)", imports, version), libs)


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_nominal_dependency_changes_invalidate_artifact(version):
    base = {"u/Types/1": library(TYPES, name="Types", version=version)}
    forwarding = library(
        "import u/Types/1 as types\nexport get()=>types.Counter.new()", version=version
    )
    libs = {**base, "user/Lib/1": forwarding}
    src = script("p=lib.get()\nplot(p.total)", version=version)
    first, link = compile_linked(src, libs)
    changed, changed_link = compile_linked(
        src, {**libs, "u/Types/1": base["u/Types/1"].replace("total=0", "total=7")}
    )
    for compiled, expected in [(first, 0), (changed, 7)]:
        runtime, cls = runtime_for(compiled)
        assert advance(runtime, cls, [1]) == [expected]
    assert first.emitted.code_hash != changed.emitted.code_hash
    assert (
        first.artifact.payload["build_determinism_identity"]
        != changed.artifact.payload["build_determinism_identity"]
    )
    assert link.dependency_hashes != changed_link.dependency_hashes
