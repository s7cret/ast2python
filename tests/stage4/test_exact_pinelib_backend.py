from __future__ import annotations

import json
from pathlib import Path

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

from ast2python import BundleInvariantError, compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest

ROOT = Path(__file__).parents[2]
PINELIB_ROOT = Path(__file__).resolve().parents[3] / "pinelib"


def _runtime_session(version: int = 6):
    from pinelib.input import InputRegistry
    from pinelib.runtime import (
        InstrumentContext,
        RuntimeLanguageContext,
        RuntimePolicies,
        RuntimeSession,
        TimeframeContext,
    )

    language = RuntimeLanguageContext(
        version,
        "2026-08-29",
        f"pine-v{version}",
        "sha256:" + "1" * 64,
        "compiler_annotation",
    )
    return RuntimeSession(
        language,
        RuntimePolicies(),
        inputs=InputRegistry([]),
        instrument=InstrumentContext(
            ticker="BTCUSDT",
            tickerid="BINANCE:BTCUSDT",
            prefix="BINANCE",
            currency="USDT",
            basecurrency="BTC",
            timezone="UTC",
            instrument_type="crypto",
            mintick=0.01,
            pointvalue=1.0,
            mincontract=0.001,
        ),
        timeframe=TimeframeContext.parse("15"),
    )


def test_production_compile_requires_explicit_target() -> None:
    bundle = build_consumer_bundle(
        '//@version=6\nindicator("x")\nplot(1)\n',
        source_name="target-required.pine",
    )
    with pytest.raises(BundleInvariantError, match="A2P_EXACT_TARGET_REQUIRED"):
        compile_consumer_bundle(bundle)


def test_exact_pinelib_target_emits_importable_executable_module() -> None:
    manifest_path = PINELIB_ROOT / "pinelib/abi/target_manifest.json"
    raw_manifest = json.loads(manifest_path.read_text())
    target = load_pinelib_target_manifest(manifest_path)
    assert target.release_acceptance == "EXACT_PINELIB_TARGET_MANIFEST_V2"
    assert target.target_version == raw_manifest["content_hash"]

    bundle = build_consumer_bundle(
        '//@version=6\nindicator("x")\nplot(1)\n',
        source_name="exact-pinelib.pine",
    )
    result = compile_consumer_bundle(bundle, target=target, module_name="exact_generated")
    code = result.emitted.code
    assert "PLAN_NODES" not in code
    assert "execute_operation" not in code
    assert "from pinelib.abi.visual import plot_v1" in code

    namespace: dict[str, object] = {}
    exec(compile(code, "exact_generated.py", "exec"), namespace)
    runtime = _runtime_session()
    from pinelib.runtime import CallbackFrame

    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    namespace["GeneratedScript"](tx).run()
    tx.commit()


@pytest.mark.parametrize("version", range(1, 7))
def test_exact_pinelib_backend_executes_all_pine_versions(version: int) -> None:
    declaration = "indicator" if version >= 5 else "study"
    source = f'//@version={version}\n{declaration}("v{version}")\nplot(1)\n'
    target = load_pinelib_target_manifest(PINELIB_ROOT / "pinelib/abi/target_manifest.json")
    result = compile_consumer_bundle(
        build_consumer_bundle(source, source_name=f"v{version}.pine"),
        target=target,
        module_name=f"generated_v{version}",
    )
    namespace: dict[str, object] = {}
    exec(compile(result.emitted.code, f"generated_v{version}.py", "exec"), namespace)
    from pinelib.runtime import CallbackFrame

    runtime = _runtime_session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    namespace["GeneratedScript"](tx).run()
    tx.commit()
