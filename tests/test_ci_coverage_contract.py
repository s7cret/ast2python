"""CI must not round sub-threshold coverage up to an accepted integer."""

import tomllib
from pathlib import Path


def test_coverage_threshold_has_sufficient_precision():
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    report = config["tool"]["coverage"]["report"]
    assert report["fail_under"] == 95
    assert report.get("precision", 0) >= 2
    assert config["tool"]["coverage"]["run"]["branch"] is True
