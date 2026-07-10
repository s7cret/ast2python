from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from backtest_engine import BacktestConfig, BacktestEngine
from backtest_engine.adapters.generated_strategy import (
    GeneratedStrategyAdapterOptions,
    make_generated_strategy_adapter,
)
from backtest_engine.models import Bar as EngineBar
from pine2ast.api import ParseOptions, parse_code, runtime_contract_v1_4_options
from pine2ast.ast.serialize import ast_to_dict
from pinelib.core import Bar as PineBar
from pinelib.request.providers import InMemoryDataProvider

from ast2python.translator import translate_ast

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("canonical_phase1_corpus.json")
CATALOG_PATH = ROOT / "ast2python" / "lowering_matrix" / "cross_layer_catalog.json"
LAYERS = ["parse", "semantic", "codegen", "runtime", "backtest"]


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _bars() -> list[EngineBar]:
    closes = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0, 105.0, 108.0]
    bars: list[EngineBar] = []
    for index, close in enumerate(closes):
        open_price = close - 1.0 if index % 2 == 0 else close + 0.5
        start = index * 60_000
        bars.append(
            EngineBar(
                time=start,
                open=open_price,
                high=max(open_price, close) + 1.0,
                low=min(open_price, close) - 1.0,
                close=close,
                volume=100.0 + index,
                time_close=start + 59_999,
            )
        )
    return bars


def _provider(engine_bars: list[EngineBar]) -> InMemoryDataProvider:
    daily = [
        PineBar(
            time=bar.time,
            time_close=bar.time_close,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in engine_bars
    ]
    return InMemoryDataProvider({("TEST", "D"): daily})


def _load_generated_module(case_id: str, code: str) -> ModuleType:
    module_name = f"phase1_corpus_{case_id.replace('-', '_')}"
    module = ModuleType(module_name)
    sys.modules[module_name] = module
    exec(compile(code, f"{module_name}.py", "exec"), module.__dict__)
    return module


def _expected_catalog(manifest: dict[str, Any]) -> dict[str, Any]:
    evidence = [
        {
            "case_id": case["id"],
            "features": sorted(case["features"]),
            "layers": LAYERS,
            "status": "DONE_VERIFIED",
        }
        for case in manifest["cases"]
    ]
    return {
        "schema_version": "ast2python.cross_layer_catalog.v1",
        "source_manifest": "tests/integration/canonical_phase1_corpus.json",
        "evidence_test": "tests/integration/test_phase1_canonical_corpus.py",
        "minimum_case_count": manifest["minimum_case_count"],
        "case_count": len(evidence),
        "evidence": evidence,
    }


def test_phase1_canonical_corpus_crosses_all_five_layers() -> None:
    manifest = _load_manifest()
    cases = manifest["cases"]
    assert len(cases) >= manifest["minimum_case_count"] >= 20
    assert len({case["id"] for case in cases}) == len(cases)

    bars = _bars()
    provider = _provider(bars)
    failures: list[str] = []

    for case in cases:
        case_id = str(case["id"])
        source = str(case["source"])
        try:
            semantic = parse_code(
                source,
                ParseOptions(
                    source_name=f"canonical:{case_id}.pine",
                    strict_builtin_namespaces=True,
                ),
            )
            assert semantic.ok, [item.to_dict() for item in semantic.diagnostics]

            parsed = parse_code(
                source,
                runtime_contract_v1_4_options(source_name=f"canonical:{case_id}.pine"),
            )
            blocking_codes = {
                item.code
                for item in parsed.diagnostics
                if str(getattr(item.severity, "value", item.severity)).lower() in {"error", "fatal"}
            }
            assert blocking_codes <= {"P2A1507"}, blocking_codes

            translated = translate_ast(
                ast_to_dict(parsed.ast),
                module_name=f"phase1_{case_id.replace('-', '_')}",
            )
            compile(translated.code, f"{case_id}.py", "exec")
            assert translated.metadata["parity_safe"] is True
            assert translated.coverage["source_map_executable_line_ratio"] >= 0.95

            module = _load_generated_module(case_id, translated.code)
            generated = module.GeneratedStrategy
            adapter = make_generated_strategy_adapter(
                generated,
                options=GeneratedStrategyAdapterOptions(
                    symbol="TEST",
                    timeframe="1",
                    data_provider=provider,
                    fail_on_config_mismatch=False,
                ),
            )
            adapter.runtime_request_data_end_ms = bars[-1].time_close
            config = BacktestConfig(
                symbol="TEST",
                timeframe="1",
                start_time=bars[0].time,
                end_time=bars[-1].time,
                commission_type="none",
                commission_value=0.0,
                default_qty_type="fixed",
                default_qty_value=1.0,
                force_close_on_end=True,
            )
            result = BacktestEngine(config).run(adapter, params={}, bars=bars)
            assert result.status == "completed"
            assert result.errors == []
            assert result.bars_processed == len(bars)
        except Exception as exc:  # pragma: no cover - aggregated assertion preserves every case id
            failures.append(f"{case_id}: {type(exc).__name__}: {exc}")

    assert failures == []
    assert json.loads(CATALOG_PATH.read_text(encoding="utf-8")) == _expected_catalog(manifest)
