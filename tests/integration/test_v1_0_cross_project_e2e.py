from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

from pinelib.core import Bar, PineRuntime, SymbolInfo, TimeframeInfo, na
from pinelib.request.providers import InMemoryDataProvider

ROOT = Path(__file__).resolve().parents[2]
PINE2AST_ROOT = ROOT.parent / "pine2ast"
PINELIB_ROOT = ROOT.parent / "pinelib"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(PINE2AST_ROOT), str(ROOT), str(PINELIB_ROOT)]
    env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return env


def _run(cmd: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=_env(), text=True, capture_output=True, check=False)


def _load_module(path: Path, name: str) -> ModuleType:
    module = ModuleType(name)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def _runtime(provider: InMemoryDataProvider | None = None) -> PineRuntime:
    return PineRuntime(
        SymbolInfo(tickerid="AAPL", timezone="UTC", session="0000-2359"),
        TimeframeInfo.from_string("1"),
        data_provider=provider,
    )


def _bars() -> list[Bar]:
    return [
        Bar(time=0, time_close=59_999, open=10, high=11, low=9, close=10, volume=100),
        Bar(time=60_000, time_close=119_999, open=20, high=21, low=19, close=20, volume=200),
    ]


def _pine_to_module(tmp_path: Path, name: str, source: str) -> tuple[ModuleType, dict[str, Any], dict[str, Any]]:
    pine = tmp_path / f"{name}.pine"
    ast_json = tmp_path / f"{name}.ast.json"
    inspect_json = tmp_path / f"{name}.inspect.json"
    out = tmp_path / "generated"
    pine.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")

    parse = _run([sys.executable, "-m", "pine2ast", "parse", str(pine), "--json", str(ast_json)])
    assert parse.returncode == 0, parse.stderr + parse.stdout
    assert ast_json.exists()

    inspect = _run([sys.executable, "-m", "pine2ast", "inspect", str(pine), "--json", str(inspect_json)])
    assert inspect.returncode == 0, inspect.stderr + inspect.stdout
    inspect_payload = json.loads(inspect_json.read_text(encoding="utf-8"))
    assert inspect_payload["ok"] is True
    assert inspect_payload["producer"]["contract"] == "pine2ast.inspect.optimizer.v1"

    translate = _run([
        sys.executable,
        "-m",
        "ast2python.cli.main",
        "translate",
        str(ast_json),
        "-o",
        str(out),
        "--module-name",
        name,
    ])
    assert translate.returncode == 0, translate.stderr + translate.stdout
    payload = json.loads(translate.stdout)
    py_path = Path(payload["paths"]["python"])
    metadata = json.loads(Path(payload["paths"]["metadata"]).read_text(encoding="utf-8"))
    assert metadata["target_runtime_contract"] == "1.4"
    assert metadata["unsupported_nodes"] == []
    return _load_module(py_path, name), metadata, inspect_payload


def test_cross_project_minimal_indicator_history_operator_na_and_plot(tmp_path: Path) -> None:
    mod, _, inspect_payload = _pine_to_module(
        tmp_path,
        "e2e_indicator",
        """
        //@version=6
        indicator("E2E indicator")
        x = close
        prev = x[1]
        bad = na + 1
        cmp = na > 1
        plot(close)
        """,
    )
    rt = _runtime()
    script = mod.GeneratedIndicator(runtime=rt)
    snapshots = script.run(_bars())
    assert [snap["bar_index"] for snap in snapshots] == [0, 1]
    assert rt.series_registry["x"]._history == [10, 20]
    assert rt.series_registry["prev"]._history == [na, 10]
    assert rt.series_registry["bad"]._history == [na, na]
    assert rt.series_registry["cmp"]._history == [False, False]
    assert inspect_payload["plots"][0]["name"] == "plot"


def test_cross_project_request_security_bounded_path(tmp_path: Path) -> None:
    mod, _, inspect_payload = _pine_to_module(
        tmp_path,
        "e2e_request",
        """
        //@version=6
        indicator("E2E request")
        htf = request.security("AAPL", "D", close)
        plot(htf)
        """,
    )
    provider = InMemoryDataProvider({
        ("AAPL", "D"): [Bar(time=0, time_close=119_999, open=100, high=101, low=99, close=100, volume=1)],
    })
    rt = _runtime(provider)
    mod.GeneratedIndicator(runtime=rt).run(_bars())
    assert rt.series_registry["htf"]._history == [na, 100]
    assert inspect_payload["request_calls"][0]["name"] == "request.security"


def test_cross_project_strategy_order_path(tmp_path: Path) -> None:
    mod, _, inspect_payload = _pine_to_module(
        tmp_path,
        "e2e_strategy",
        """
        //@version=6
        strategy("E2E strategy")
        if close > open
            strategy.entry("L", strategy.long)
        """,
    )
    rt = _runtime()
    script = mod.GeneratedStrategy(runtime=rt)
    script.run([Bar(time=0, time_close=59_999, open=9, high=11, low=8, close=10, volume=100)])
    assert script.ctx.pending_orders
    assert script.ctx.pending_orders[0].id == "L"
    assert inspect_payload["script"]["type"] == "strategy"
    assert inspect_payload["strategy_calls"][0]["name"] == "strategy.entry"


def test_cross_project_visual_recorder_path_uses_current_bar_index(tmp_path: Path) -> None:
    mod, _, inspect_payload = _pine_to_module(
        tmp_path,
        "e2e_visual",
        """
        //@version=6
        indicator("E2E visual")
        var line ln = line.new(0, close, 1, close)
        line.set_xy1(ln, bar_index, close)
        plot(close)
        """,
    )
    rt = _runtime()
    mod.GeneratedIndicator(runtime=rt).run(_bars())
    assert [event.action for event in rt.visual.events[:3]] == ["new", "set", "set"]
    first_set_args = rt.visual.events[1].attrs["_args"]
    second_set_args = rt.visual.events[2].attrs["_args"]
    assert first_set_args == (0, 10)
    assert second_set_args == (1, 20)
    assert inspect_payload["drawings"][0]["name"] == "line.new"
