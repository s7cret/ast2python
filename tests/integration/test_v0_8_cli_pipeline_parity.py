from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ast2python.ast.schema import load_ast
from ast2python.translator import translate_ast

FIXTURES = Path("[local-home]/pine2ast/tests/fixtures/golden_ast/valid/real_world_smoke")


def test_v0_8_translate_many_cli_matches_api_and_writes_artifacts(tmp_path: Path) -> None:
    inputs = [
        FIXTURES / "01_ma_indicator.ast.json",
        FIXTURES / "13_input_source_strategy_state.ast.json",
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", "translate-many", *(str(path) for path in inputs), "-o", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert [item["module"] for item in payload["modules"]] == [path.stem for path in inputs]
    for path in inputs:
        api = translate_ast(load_ast(path), module_name=path.stem)
        generated = (tmp_path / f"{path.stem}.py").read_text(encoding="utf-8")
        assert generated == api.code
        assert (tmp_path / f"{path.stem}.meta.json").exists()
        assert (tmp_path / f"{path.stem}.coverage.json").exists()
        assert (tmp_path / f"{path.stem}.sourcemap.json").exists()
        compile(generated, str(path), "exec")


def test_v0_8_runtime_contract_metadata_shape_is_pipeline_stable() -> None:
    result = translate_ast(load_ast(FIXTURES / "13_input_source_strategy_state.ast.json"), module_name="state_strategy")
    metadata = result.metadata
    assert metadata["generator_milestone"] == "v1.0.0"
    assert metadata["target_runtime_contract"] == "1.4"
    assert metadata["class_name"] == "GeneratedStrategy"
    assert "strategy.entry" in metadata["used_builtins"]
    assert all("code" in item and "severity" in item for item in metadata["diagnostics"])
    assert result.coverage["source_map_executable_line_ratio"] >= 0.95
