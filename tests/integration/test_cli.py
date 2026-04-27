import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "ast"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ast2python.cli.main", *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_cli_validate_and_translate(tmp_path):
    validate = run_cli("validate", str(FIXTURES / "minimal_indicator.ast.json"))
    assert validate.returncode == 0
    payload = json.loads(validate.stdout)
    assert payload["ok"] is True

    output_dir = tmp_path / "generated"
    translate = run_cli(
        "translate",
        str(FIXTURES / "minimal_indicator.ast.json"),
        "-o",
        str(output_dir),
        "--module-name",
        "minimal_indicator",
    )
    assert translate.returncode == 0
    files = json.loads(translate.stdout)["paths"]
    assert Path(files["python"]).exists()
    assert Path(files["metadata"]).exists()
    assert Path(files["source_map"]).exists()
    assert Path(files["coverage"]).exists()
