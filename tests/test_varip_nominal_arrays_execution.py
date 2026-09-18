"""Documented nominal arrays through generated code and exact target admission."""
from copy import deepcopy
from dataclasses import replace
from importlib.resources import files
import json

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame
from pinelib.state.checkpoint import from_portable, sha

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_rc6_input_metadata import compile_source
from tests.test_locked_library_execution import runtime_for

CAPABILITY = "compiler.varip_nominal_arrays.v1"
PROFILES = ["    int n\n", "    int n\n    varip int ticks\n", "    array<int> values\n",
            "    matrix<float> grid\n", "    int n\n    varip int ticks\n    array<int> values\n    matrix<float> grid\n"]


def source(body, version):
    return f'//@version={version}\nindicator("nominal arrays")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("fields", PROFILES)
def test_empty_array_checks_declarations_before_any_udt_exists(version, fields):
    compiled = compile_source(source("type Counter\n" + fields + "varip array<Counter> bag=array.new<Counter>()\nplot(array.size(bag))", version))
    assert CAPABILITY in compiled.plan.required_capabilities
    runtime, cls = runtime_for(compiled)
    assert callback(runtime, cls, 0, 0) == [0]


def callback(runtime, cls, sequence, bar, *, realtime=False, final=True, deferred=False, abort=False):
    tx = runtime.begin(CallbackFrame("REALTIME_TICK" if realtime else "HISTORICAL_EVAL", sequence,
        bar_index=bar, realtime=realtime, final_tick=final, defer_bar_commit=deferred))
    cls(tx).run()
    values = [from_portable(event.payload["series"]) for event in runtime.visuals.working]
    tx.abort() if abort else tx.commit()
    return values


BODY = """type Counter
    int n=0
    varip int ticks=0
    array<int> values
    matrix<float> grid
var Counter c=Counter.new(values=array.new<int>(1,0),grid=matrix.new<float>(1,1,0.0))
varip array<Counter> bag=array.new<Counter>()
if barstate.isrealtime
    array.push(bag,c)
    c.n+=1
    c.ticks+=1
    array.set(c.values,0,array.get(c.values,0)+1)
    matrix.set(c.grid,0,0,matrix.get(c.grid,0,0)+1)
plot(array.size(bag))
plot(c.n)
plot(c.ticks)
plot(array.get(c.values,0))
plot(matrix.get(c.grid,0,0))"""


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_generated_alias_trial_abort_checkpoint_and_same_sequence_retry(version, compact):
    compiled = compile_source(source(BODY, version))
    runtime, cls = runtime_for(compiled)
    runtime.commit_full_identity = not compact
    assert callback(runtime, cls, 0, 0) == [0, 0, 0, 0, 0.0]
    assert callback(runtime, cls, 1, 1, realtime=True, final=False) == [1, 1, 1, 1, 1.0]
    success = deepcopy(runtime.transcript.to_dict())
    assert callback(runtime, cls, 2, 1, realtime=True, final=False, abort=True) == [2, 1, 2, 1, 1.0]
    assert runtime.sequence == 1 and runtime.transcript.to_dict() == success
    saved = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    clone, _ = runtime_for(compiled)
    clone.commit_full_identity = not compact
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        assert callback(current, cls, 2, 1, realtime=True) == [3, 1, 3, 1, 1.0]
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_generated_historical_fill_uses_real_deferred_bar_publication(version, compact):
    body = """type Counter
    int n=0
    varip int ticks=0
var Counter c=Counter.new()
varip array<Counter> bag=array.new<Counter>()
array.push(bag,c)
c.n+=1
c.ticks+=1
plot(array.size(bag))
plot(c.n)
plot(c.ticks)"""
    compiled = compile_source(source(body, version))
    runtime, cls = runtime_for(compiled)
    runtime.commit_full_identity = not compact
    assert callback(runtime, cls, 0, 0, deferred=True) == [1, 1, 1]
    assert callback(runtime, cls, 1, 0, deferred=True) == [2, 1, 1]
    # Ordinary binding c is reinitialized before its first bar publication.
    runtime.finalize_bar(0)
    clone, _ = runtime_for(compiled)
    clone.commit_full_identity = not compact
    clone.restore(json.loads(json.dumps(runtime.checkpoint().to_dict())))
    for current in (runtime, clone):
        assert callback(current, cls, 3, 1, deferred=True) == [3, 2, 2]
        assert callback(current, cls, 4, 1, deferred=True) == [4, 2, 3]
        current.finalize_bar(1)
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("field", ["Side value", "array<Side> values", "Child value", "array<Child> values",
    "Counter next", "map<string,int> values", "varip array<int> values", "varip matrix<float> values"])
def test_deferred_nominal_field_profiles_still_fail_closed(version, field):
    body = "enum Side\n    one\ntype Child\n    int n\ntype Counter\n    " + field + "\nvarip array<Counter> bag=array.new<Counter>()"
    with pytest.raises(BundleInvariantError, match="A2P_VARIP_REFERENCE_TYPE"):
        compile_source(source(body, version))


@pytest.mark.parametrize("capability", [CAPABILITY, "compiler.nominal_registry.v1", "compiler.varip_reference_bindings.v1"])
def test_generated_nominal_arrays_require_each_exact_target_capability(capability):
    target = load_pinelib_target_manifest()
    target = replace(target, capabilities=target.capabilities - {capability})
    with pytest.raises(BundleInvariantError, match="A2P_PLAN_CAPABILITY"):
        compile_consumer_bundle(build_consumer_bundle(source("type C\n    int n\nvarip array<C> bag=array.new<C>()", 6)), target=target)


@pytest.mark.parametrize("change", ["missing", "extra", "bool_revision", "float_version", "wrong_profile", "missing_registry", "missing_fundamental", "bool_dependency_revision", "float_dependency_version"])
def test_manifest_contract_is_closed_exact_and_requires_dependencies(tmp_path, change):
    raw = json.loads(files("pinelib.abi").joinpath("target_manifest.json").read_text())
    if change == "missing": del raw["compiled_varip_nominal_arrays"]
    elif change == "extra": raw["compiled_varip_nominal_arrays"]["extra"] = 1
    elif change == "bool_revision": raw["compiled_varip_nominal_arrays"]["revision"] = True
    elif change == "float_version": raw["compiled_varip_nominal_arrays"]["min_pine_version"] = 5.0
    elif change == "wrong_profile": raw["compiled_varip_nominal_arrays"]["field_profile"] = "any-recursive-reference"
    elif change == "missing_registry": del raw["compiled_nominal_registry"]
    elif change == "bool_dependency_revision": raw["compiled_varip_reference_storage"]["revision"] = True
    elif change == "float_dependency_version": raw["compiled_varip_reference_storage"]["min_pine_version"] = 5.0
    else: del raw["compiled_varip_reference_storage"]
    raw["content_hash"] = sha({k: v for k, v in raw.items() if k != "content_hash"})
    path = tmp_path / "target.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert CAPABILITY not in load_pinelib_target_manifest(path).capabilities


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("declaration", ["varip bag=array.new<Counter>()", "varip array<Counter> bag=na"])
def test_inferred_and_missing_array_declarations_still_record_exact_capability(version, declaration):
    body = "type Counter\n    int n\n" + declaration + "\n"
    compiled = compile_source(source(body, version))
    assert CAPABILITY in compiled.plan.required_capabilities
    assert CAPABILITY in compiled.artifact.payload["required_capabilities"]
    runtime, cls = runtime_for(compiled)
    callback(runtime, cls, 0, 0)
    clone, _ = runtime_for(compiled)
    clone.restore(runtime.checkpoint().to_dict())
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
def test_linked_library_udt_uses_exact_linked_declaration_profile(version):
    from tests.test_locked_library_execution import compile_linked, library, script
    compiled, _ = compile_linked(script("varip array<lib.Counter> bag=array.new<lib.Counter>()\nplot(array.size(bag))", version=version),
        {"user/Lib/1": library("export type Counter\n    int n\n    array<int> values", version=version)})
    assert CAPABILITY in compiled.artifact.payload["required_capabilities"]
    runtime, cls = runtime_for(compiled)
    assert callback(runtime, cls, 0, 0) == [0]
