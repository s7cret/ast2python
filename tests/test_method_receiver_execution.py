"""Admitted receiver constraints reuse normal generated execution and state."""

import json

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.admission import BundleAdmissionService
from ast2python.artifacts import verify_generated_artifact_v3
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import compile_linked, runtime_for

CAP = "method_receiver_qualifiers_v1"
CASES = [
    ("simple", "method add(simple int self)=>self+1\na=2\nplot(a.add())", [3, 3, 3]),
    ("input", "method add(simple int self)=>self+1\na=input.int(2)\nplot(a.add())", [3, 3, 3]),
    ("series", "method add(series int self)=>self+1\nplot(bar_index.add())", [1, 2, 3]),
    ("default", "method add(simple int self,int n=3)=>self+n\na=2\nplot(a.add())", [5, 5, 5]),
    (
        "named",
        "method pack(simple int self,int step=1,int offset=2)=>self*100+step*10+offset\na=1\nplot(a.pack(offset=3,step=2))",
        [123, 123, 123],
    ),
    (
        "tuple",
        "method pair(simple int self)=>[self,self+1]\na=2\n[x,y]=a.pair()\nplot(x)\nplot(y)",
        [2, 3, 2, 3, 2, 3],
    ),
    (
        "custom_nz_receiver",
        "method nz(simple bool self)=>self\na=true\nplot(a.nz()?1:0)",
        [1, 1, 1],
    ),
    (
        "custom_nz_argument",
        "method nz(simple bool self,simple bool other)=>other\na=true\nplot(a.nz(false)?1:0)",
        [0, 0, 0],
    ),
    (
        "receiver_once",
        "next()=>\n    var int n=0\n    n+=1\n    n\nmethod add(series int self)=>self+10\nplot(next().add())",
        [11, 12, 13],
    ),
    (
        "series_reference",
        "method sizeOf(series array<int> self)=>self.size()\na=array.new<int>(1,2)\nplot(a.sizeOf())",
        [1, 1, 1],
    ),
]


def compile_body(body, version):
    text = f'//@version={version}\nindicator("Receiver execution")\n{body}\n'
    bundle = build_consumer_bundle(text, producer_commit="a" * 40)
    admitted = BundleAdmissionService().admit(bundle, expected_producer_commit="a" * 40)
    assert CAP in admitted.required_capabilities
    result = compile_consumer_bundle(
        bundle,
        target=load_pinelib_target_manifest(),
        producer_commit="b" * 40,
        expected_pine2ast_commit="a" * 40,
    )
    assert CAP not in result.plan.required_capabilities
    assert CAP not in result.artifact.payload["required_capabilities"]
    assert set(admitted.required_capabilities) - {CAP} <= result.plan.required_capabilities
    verify_generated_artifact_v3(result.artifact.payload, emitted=result.emitted, plan=result.plan)
    return result


def tick(runtime, cls, sequence, bar, *, realtime=False, final=True, abort=False):
    tx = runtime.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            sequence,
            bar_index=bar,
            realtime=realtime,
            final_tick=final,
        )
    )
    cls(tx).run()
    out = [from_portable(e.payload["series"]) for e in runtime.visuals.working]
    if abort:
        tx.abort()
    else:
        tx.commit()
    return out


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name,body,expected", CASES, ids=[row[0] for row in CASES])
def test_source_free_admission_generated_values_and_json_continuation(
    version, name, body, expected
):
    result = compile_body(body, version)
    whole, cls = runtime_for(result)
    for bar in range(3):
        tick(whole, cls, bar, bar)
    assert [from_portable(e.payload["series"]) for e in whole.visuals.committed] == expected
    split, _ = runtime_for(result)
    tick(split, cls, 0, 0)
    resumed, _ = runtime_for(result)
    resumed.restore(json.loads(json.dumps(split.checkpoint().to_dict())))
    for bar in (1, 2):
        tick(resumed, cls, bar, bar)
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_once_evaluated_receiver_survives_abort_retry_without_duplicate_state(version):
    body = next(row[1] for row in CASES if row[0] == "receiver_once")
    result = compile_body(body, version)
    runtime, cls = runtime_for(result)
    assert tick(runtime, cls, 0, 0, abort=True)[-1] == 11
    assert tick(runtime, cls, 0, 0)[-1] == 11
    assert tick(runtime, cls, 1, 1)[-1] == 12
    clean, _ = runtime_for(result)
    tick(clean, cls, 0, 0)
    tick(clean, cls, 1, 1)
    assert runtime.checkpoint().to_dict() == clean.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_method_local_var_rolls_back_after_open_bar_json_restore(version):
    body = (
        "method count(simple int self)=>\n    var int n=0\n    n+=self\n    n\na=2\nplot(a.count())"
    )
    result = compile_body(body, version)
    runtime, cls = runtime_for(result)
    assert tick(runtime, cls, 0, 0)[-1] == 2
    assert tick(runtime, cls, 1, 1, realtime=True, final=False)[-1] == 4
    restored, _ = runtime_for(result)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for session in (runtime, restored):
        assert tick(session, cls, 2, 1, realtime=True, final=False)[-1] == 4
        assert tick(session, cls, 3, 1, realtime=True)[-1] == 4
        assert tick(session, cls, 4, 2)[-1] == 6
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_admission_only_capability_preserves_nominal_registry_and_varip_runtime_contracts(version):
    body = "type P\n    float n=1.0\nvarip array<P> values=array.new<P>()\nmethod sizeOf(series array<P> self)=>self.size()\nplot(values.sizeOf())"
    result = compile_body(body, version)
    required = set(result.artifact.payload["required_capabilities"])
    assert {
        "compiler.nominal_types.v1",
        "compiler.nominal_registry.v1",
        "compiler.varip_nominal_arrays.v1",
    } <= required
    runtime, cls = runtime_for(result)
    assert runtime.nominal_registry is not None
    assert tick(runtime, cls, 0, 0)[-1] == 0


def test_v6_reference_annotation_is_preserved_without_simple_reference_runtime_value():
    result = compile_body(
        "method sizeOf(simple array<int> self)=>self.size()\na=array.new<int>(1,2)\nplot(a.sizeOf())",
        6,
    )
    runtime, cls = runtime_for(result)
    assert tick(runtime, cls, 0, 0)[-1] == 1


@pytest.mark.parametrize("version", [5, 6])
def test_receiver_proof_composes_with_verified_library_context_and_checkpoint(version):
    library = f'//@version={version}\nlibrary("Lib")\nexport two()=>2\n'
    source = f'//@version={version}\nindicator("Linked receiver")\nimport qa/Lib/1 as lib\nmethod add(simple int self)=>self+1\na=lib.two()\nplot(a.add())\n'
    result, linked = compile_linked(source, {"qa/Lib/1": library})
    assert CAP not in result.plan.required_capabilities
    assert "library_qualifier_context_v1" in result.plan.required_capabilities
    assert "@linkage" in result.artifact.payload["external_library_dependency_hashes"]
    runtime, cls = runtime_for(result)
    assert tick(runtime, cls, 0, 0)[-1] == 3
    restored, _ = runtime_for(result)
    restored.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for session in (runtime, restored):
        assert tick(session, cls, 1, 1)[-1] == 3
    assert runtime.checkpoint().to_dict() == restored.checkpoint().to_dict()
