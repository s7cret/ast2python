from __future__ import annotations

import json

from ast2python.cli.main import main
from tests.conftest import FIXTURE_ROOT


def test_cli_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "5.0.0rc6"


def test_validate_bundle_cli(capsys) -> None:
    path = FIXTURE_ROOT / "pine-v6-consumer-bundle.json"
    assert main(["validate-bundle", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["pine_version"] == 6


def test_inspect_bundle_cli(capsys) -> None:
    path = FIXTURE_ROOT / "pine-v4-consumer-bundle.json"
    assert main(["inspect-bundle", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version_context"]["pine_version"] == 4
    assert payload["runnable_output_allowed"] is False
