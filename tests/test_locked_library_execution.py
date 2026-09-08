"""Linked Pine libraries execute the existing compiler/runtime, with pinned provenance."""

import json
from copy import deepcopy

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.input import InputRegistry
from pinelib.reference.registry import NominalTypeRegistry
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.artifacts import admitted_nominal_registry, verify_generated_artifact_v3
from ast2python.errors import BundleInvariantError
from ast2python.lowering import load_pinelib_target_manifest


def library(body, name="Lib", version=6):
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


def script(body, imports="import user/Lib/1 as lib", version=6):
    return f'//@version={version}\nindicator("locked libraries")\n{imports}\n{body}\n'


def compile_linked(source, libs):
    linked = link_libraries(source, LibraryStore.create(libs))
    bundle = build_consumer_bundle(linked.code, producer_commit="a" * 40, linked_source=linked)
    return (
        compile_consumer_bundle(
            bundle,
            linked_source=linked,
            target=load_pinelib_target_manifest(),
            producer_commit="b" * 40,
            expected_pine2ast_commit="a" * 40,
        ),
        linked,
    )


def runtime_for(compiled, overrides=None):
    verify_generated_artifact_v3(
        compiled.artifact.payload, emitted=compiled.emitted, plan=compiled.plan
    )
    ns = {}
    exec(compile(compiled.emitted.code, "linked_library.py", "exec"), ns)
    metadata = ns["SCRIPT_METADATA"]
    runtime = RuntimeSession(
        RuntimeLanguageContext(
            metadata["pine_version"],
            "tests",
            f"pine-v{metadata['pine_version']}",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        inputs=InputRegistry.from_descriptors(metadata["inputs"], overrides),
        nominal_registry=admitted_nominal_registry(
            ns, compiled.artifact.payload, admit_registry=NominalTypeRegistry.from_json
        ),
    )
    return runtime, ns["GeneratedScript"]


def advance(runtime, cls, closes, start=0):
    for i, c in enumerate(closes, start):
        tx = runtime.begin(
            CallbackFrame("HISTORICAL_EVAL", i, bar_index=i),
            values=BarValues(c, c + 1, c - 1, c, 1, i * 60000, (i + 1) * 60000 - 1),
        )
        cls(tx).run()
        tx.commit()
    return [from_portable(e.payload["series"]) for e in runtime.visuals.committed]


@pytest.mark.parametrize("version", [5, 6])
def test_public_private_constant_closure_executes_but_example_code_does_not(version):
    libs = {
        "user/Lib/1": library(
            "K=2\nhelper(float x)=>x*K\nexport f(float x)=>helper(x)\nplot(close*999)",
            version=version,
        )
    }
    result, _ = compile_linked(script("plot(lib.f(close))", version=version), libs)
    r, cls = runtime_for(result)
    assert advance(r, cls, [1, 2, 3]) == [2, 4, 6]
    verify_generated_artifact_v3(
        result.artifact.payload,
        emitted=result.emitted,
        plan=result.plan,
        target=load_pinelib_target_manifest(),
    )


@pytest.mark.parametrize("version", [5, 6])
def test_independent_written_imported_calls_and_local_var_restore(version):
    libs = {
        "user/Lib/1": library(
            "export count(int step=1)=>\n    var int n=0\n    n+=step\n    n", version=version
        )
    }
    source = script("plot(lib.count())\nplot(lib.count(step=10))", version=version)
    compiled, _ = compile_linked(source, libs)
    whole, cls = runtime_for(compiled)
    assert advance(whole, cls, [1, 2, 3]) == [1, 10, 2, 20, 3, 30]
    split, _ = runtime_for(compiled)
    advance(split, cls, [1])
    state = json.loads(json.dumps(split.checkpoint().to_dict()))
    resumed, _ = runtime_for(compiled)
    resumed.restore(state)
    advance(resumed, cls, [2, 3], start=1)
    assert resumed.checkpoint().to_dict() == whole.checkpoint().to_dict()


def test_same_call_in_loop_and_conditional_history_remain_context_local():
    libs = {"user/Lib/1": library("export count()=>\n    var int n=0\n    n+=1\n    n")}
    compiled, _ = compile_linked(script("a=0\nfor i=1 to 3\n    a:=lib.count()\nplot(a)"), libs)
    r, cls = runtime_for(compiled)
    assert advance(r, cls, [1, 2, 3]) == [3, 6, 9]


def test_ta_and_inputs_execute_inside_imported_function():
    libs = {"user/Lib/1": library("export avg(float x, simple int n)=>ta.sma(x,n)")}
    compiled, _ = compile_linked(script("n=input.int(2)\nplot(lib.avg(close,n))"), libs)
    r, cls = runtime_for(compiled)
    out = advance(r, cls, [1, 2, 3, 4])
    assert is_na(out[0]) and out[1:] == [1.5, 2.5, 3.5]
    r, cls = runtime_for(compiled, {"n": 3})
    out = advance(r, cls, [1, 2, 3, 4])
    assert all(is_na(v) for v in out[:2]) and out[2:] == [2, 3]


def test_transitive_diamond_and_colliding_private_names():
    libs = {
        "u/Common/1": library("hidden(float x)=>x*2\nexport f(float x)=>hidden(x)", "Common"),
        "u/A/1": library(
            "import u/Common/1 as c\nhidden(float x)=>c.f(x)+1\nexport f(float x)=>hidden(x)", "A"
        ),
        "u/B/1": library(
            "import u/Common/1 as c\nhidden(float x)=>c.f(x)+10\nexport f(float x)=>hidden(x)", "B"
        ),
    }
    compiled, _ = compile_linked(
        script(
            "hidden=500\nplot(a.f(close))\nplot(b.f(close))", "import u/A/1 as a\nimport u/B/1 as b"
        ),
        libs,
    )
    r, cls = runtime_for(compiled)
    assert advance(r, cls, [1, 2, 3]) == [3, 12, 5, 14, 7, 16]


def test_two_publication_revisions_and_two_aliases_are_separate_calls():
    libs = {
        "user/Lib/1": library("export f(float x)=>x+1"),
        "user/Lib/2": library("export f(float x)=>x+10"),
    }
    compiled, _ = compile_linked(
        script(
            "plot(a.f(close))\nplot(b.f(close))\nplot(c.f(close))",
            "import user/Lib/1 as a\nimport user/Lib/2 as b\nimport user/Lib/1 as c",
        ),
        libs,
    )
    r, cls = runtime_for(compiled)
    assert advance(r, cls, [1, 2]) == [2, 11, 2, 3, 12, 3]


def test_unused_store_entries_do_not_change_artifact_but_transitive_source_does():
    libs = {"user/Lib/1": library("export f(float x)=>x+1")}
    a, la = compile_linked(script("plot(lib.f(close))"), libs)
    b, lb = compile_linked(
        script("plot(lib.f(close))"), {**libs, "user/Other/1": library("export f()=>7", "Other")}
    )
    assert a.artifact.to_dict() == b.artifact.to_dict() and la == lb
    c, _ = compile_linked(
        script("plot(lib.f(close))"), {"user/Lib/1": libs["user/Lib/1"] + "// corrected source\n"}
    )
    assert c.artifact.payload["content_hash"] != a.artifact.payload["content_hash"]
    assert (
        c.artifact.payload["build_determinism_identity"]
        != a.artifact.payload["build_determinism_identity"]
    )


def test_unresolved_imports_are_not_silently_ignored():
    source = script("plot(close)")
    with pytest.raises(
        (ConsumerBundleError, BundleInvariantError), match="library|import|frontend"
    ):
        compile_consumer_bundle(
            build_consumer_bundle(source, producer_commit="a" * 40),
            target=load_pinelib_target_manifest(),
            producer_commit="b" * 40,
            expected_pine2ast_commit="a" * 40,
        )


def test_link_receipt_must_match_compiler_input_bundle():
    linked = link_libraries(
        script("plot(lib.f(close))"),
        LibraryStore.create({"user/Lib/1": library("export f(float x)=>x")}),
    )
    bundle = build_consumer_bundle(
        '//@version=6\nindicator("other")\nplot(close)', producer_commit="a" * 40
    )
    with pytest.raises(BundleInvariantError, match="bundle source differs"):
        compile_consumer_bundle(
            bundle,
            linked_source=linked,
            target=load_pinelib_target_manifest(),
            producer_commit="b" * 40,
            expected_pine2ast_commit="a" * 40,
        )


def test_artifact_dependencies_are_in_build_identity_even_after_outer_rehash():
    import hashlib

    result, _ = compile_linked(
        script("plot(lib.f(close))"), {"user/Lib/1": library("export f(float x)=>x")}
    )
    artifact = deepcopy(result.artifact.to_dict())
    assert "@linkage" in artifact["external_library_dependency_hashes"]
    artifact["external_library_dependency_hashes"]["user/Lib/1"] = "sha256:" + "0" * 64
    artifact["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes({k: v for k, v in artifact.items() if k != "content_hash"})
        ).hexdigest()
    )
    with pytest.raises(BundleInvariantError, match="build_manifest_hash"):
        verify_generated_artifact_v3(artifact)


@pytest.mark.parametrize("expression", ["lib.f(bar_index)", "lib.f(close)"])
def test_simple_parameter_cannot_accept_series(expression):
    with pytest.raises((ConsumerBundleError, BundleInvariantError)):
        compile_linked(
            script("plot(" + expression + ")"), {"user/Lib/1": library("export f(simple int x)=>x")}
        )


def test_external_exports_cannot_supply_const_required_plot_titles():
    with pytest.raises((ConsumerBundleError, BundleInvariantError)):
        compile_linked(
            script("plot(close,title=lib.f())"), {"user/Lib/1": library('export f()=>"not const"')}
        )


def test_root_library_source_map_can_be_composed_to_original_export_and_call():
    compiled, linked = compile_linked(
        script("plot(lib.f(close))"), {"user/Lib/1": library("export f(float x)=>x*2")}
    )
    origins = set()
    for row in compiled.emitted.source_map.entries:
        if row.source_span:
            found = linked.original_location(row.source_span["start_offset"])
            if found:
                origins.add(found["source"])
    assert origins == {"user/Lib/1", "<memory>"}


@pytest.mark.parametrize("version", [5, 6])
def test_exported_default_can_read_chart_builtin_without_global_capture(version):
    libs = {"user/Lib/1": library("export f(float x=high)=>x", version=version)}
    compiled, linked = compile_linked(
        script("plot(lib.f())\nplot(lib.f(close))", version=version), libs
    )
    linked.verify()
    r, cls = runtime_for(compiled)
    assert advance(r, cls, [1, 2, 3]) == [2, 1, 3, 2, 4, 3]
