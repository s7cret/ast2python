"""OP-02: compile literal admission metadata and execute the actual generated code."""

from __future__ import annotations

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na
from pinelib.input import InputRegistry
from pinelib.runtime.metadata import BarValues
from pinelib.state.checkpoint import from_portable

from ast2python import compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest


def compile_source(source):
    return compile_consumer_bundle(
        build_consumer_bundle(source, source_name="inputs.pine", producer_commit="1" * 40),
        target=load_pinelib_target_manifest(),
        module_name="input_case",
        expected_pine2ast_commit="1" * 40,
        producer_commit="2" * 40,
    )


def run_source(source, overrides=None, closes=range(1, 9)):
    result = compile_source(source)
    namespace = {}
    exec(compile(result.emitted.code, "input_case.py", "exec"), namespace)
    metadata = namespace["SCRIPT_METADATA"]
    inputs = InputRegistry.from_descriptors(metadata["inputs"], overrides)
    runtime = RuntimeSession(
        RuntimeLanguageContext(
            metadata["pine_version"],
            "2026-09-05",
            f"pine-v{metadata['pine_version']}",
            "sha256:" + "a" * 64,
            "compiler_annotation",
        ),
        inputs=inputs,
    )
    for i, close in enumerate(closes):
        tx = runtime.begin(
            CallbackFrame("HISTORICAL_EVAL", i, bar_index=i),
            values=BarValues(
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=0,
                time=i * 60000,
                time_close=(i + 1) * 60000 - 1,
            ),
        )
        namespace["GeneratedScript"](tx).run()
        tx.commit()
    return runtime, metadata, result


def test_sma_input_reaches_generated_runtime_and_changes_value():
    source = '//@version=6\nindicator("inputs")\nn=input.int(2,"Length",minval=1)\nplot(ta.sma(close,n))\n'
    short, _, _ = run_source(source)
    long, _, _ = run_source(source, {"n": 7})
    assert short.visuals.committed[-1].payload["series"] == 7.5
    assert long.visuals.committed[-1].payload["series"] == 5.0
    assert short.inputs.identity_hash != long.inputs.identity_hash
    assert is_na(from_portable(long.visuals.committed[0].payload["series"]))


@pytest.mark.parametrize("version", range(1, 7))
def test_generic_input_all_versions(version):
    decl = "indicator" if version >= 5 else "study"
    src = f'//@version={version}\n{decl}("legacy")\nn=input(2,"Length")\nplot(n)\n'
    runtime, metadata, result = run_source(src, {"n": 0}, [1])
    assert runtime.visuals.committed[-1].payload["series"] == 0
    assert list(metadata["inputs"].values())[0]["default"] == 2
    assert result.emitted.script_metadata == metadata


def test_same_titles_do_not_alias_and_false_zero_empty_overrides_survive():
    src = '//@version=6\nindicator("same")\na=input.int(2,"same")\nb=input.int(3,"same")\nok=input.bool(true,"ok")\ns=input.string("hello","text")\nplot(a+b)\n'
    runtime, metadata, _ = run_source(src, {"a": 0, "b": 7, "ok": False, "s": ""}, [1])
    assert runtime.visuals.committed[-1].payload["series"] == 7
    assert len(metadata["inputs"]) == 4
    by_alias = {row.get("alias"): key for key, row in metadata["inputs"].items()}
    assert runtime.inputs.get(by_alias["ok"]) is False
    assert runtime.inputs.get(by_alias["s"]) == ""
    with pytest.raises(Exception, match="unknown or ambiguous"):
        InputRegistry.from_descriptors(metadata["inputs"], {"same": 2})


def test_source_input_is_a_series_not_a_ticker_or_name_string():
    src = '//@version=6\nindicator("source")\ns=input.source(close,"Source")\nplot(s)\n'
    runtime, _, _ = run_source(src, {"s": "high"}, [10])
    assert runtime.visuals.committed[-1].payload["series"] == 11


@pytest.mark.parametrize("version,value", [(5, 2), (6, 2.5)])
def test_metadata_uses_versioned_constant_facts(version, value):
    src = f'//@version={version}\nindicator("const")\nx=input.float(5/2,"x")\nplot(x)\n'
    runtime, _, _ = run_source(src, closes=[1])
    assert runtime.visuals.committed[-1].payload["series"] == value


def test_strategy_declaration_is_preserved_and_code_hash_binds_metadata():
    src = '//@version=6\nstrategy("props",default_qty_value=7,margin_long=0,commission_type=strategy.commission.percent)\nplot(close)\n'
    result = compile_source(src)
    args = result.emitted.script_metadata["declaration"]["arguments"]
    assert args["default_qty_value"] == 7 and args["margin_long"] == 0
    assert args["commission_type"] == "strategy.commission.percent"
    other = compile_source(src.replace("value=7", "value=8"))
    assert result.emitted.code_hash != other.emitted.code_hash
