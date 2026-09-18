from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from ast2python import AnalysisOnlyError, open_compilation_session
from ast2python.cli.main import main as cli_main
from ast2python.distribution import (
    build_distribution_manifest,
    create_source_zip,
    iter_distribution_files,
)
from ast2python.distribution import (
    main as distribution_main,
)
from ast2python.release import build_release_report
from ast2python.release import main as release_main
from tests.conftest import FIXTURE_ROOT, load_bundle
from tools.regenerate_consumer_bundles import RegenerationCase, regenerate_cases

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_manifest_and_deterministic_zip(tmp_path: Path, capsys) -> None:
    manifest = build_distribution_manifest(ROOT)
    assert manifest.ok
    payload = manifest.to_dict()
    assert payload["package_version"] == "5.0.0rc6"
    assert payload["file_count"] == len(manifest.files)
    assert "README.md" in manifest.files

    output = tmp_path / "source.zip"
    report = create_source_zip(ROOT, output, root_name="ast2python-test")
    assert report["file_count"] == len(manifest.files)
    with zipfile.ZipFile(output) as archive:
        assert "ast2python-test/README.md" in archive.namelist()
        assert all("__pycache__" not in name for name in archive.namelist())

    assert distribution_main(["manifest", "--root", str(ROOT)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] is True
    output2 = tmp_path / "source2.zip"
    assert (
        distribution_main(
            ["build-zip", "--root", str(ROOT), "--output", str(output2), "--root-name", "x"]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["root_name"] == "x"


def test_distribution_invalid_roots_and_exclusions(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing"
    assert iter_distribution_files(missing) == ()
    report = build_distribution_manifest(missing)
    assert not report.ok
    assert any(item.code == "missing_root" for item in report.findings)
    assert distribution_main(["manifest", "--root", str(missing)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    with pytest.raises(ValueError, match="not clean"):
        create_source_zip(missing, tmp_path / "bad.zip")

    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "README.md").write_text("x", encoding="utf-8")
    (partial / "drop.pyc").write_bytes(b"x")
    (partial / "build").mkdir()
    (partial / "build" / "drop.txt").write_text("x", encoding="utf-8")
    manifest = build_distribution_manifest(partial)
    assert not manifest.ok
    assert "drop.pyc" not in manifest.files
    assert all(not name.startswith("build/") for name in manifest.files)


def test_release_report_valid_and_cli(capsys) -> None:
    report = build_release_report(ROOT)
    assert report.ok
    payload = report.to_dict()
    assert payload["consumer_contract"]["schema_id"] == "pine2ast.consumer_bundle.v1"
    assert payload["compiler_architecture"]["source_map"] == "openpine.source_map.v2"
    assert payload["runnable_output_available"] is True
    assert release_main(["--root", str(ROOT)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_release_report_detects_manifest_problems(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    shutil.copytree(
        ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage")
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text()
        .replace('version = "5.0.0rc6"', 'version = "0"')
        .replace('"pine2ast==5.0.0rc6"', '"pine2ast"'),
        encoding="utf-8",
    )
    (root / "ast2python" / "__init__.py").write_text("", encoding="utf-8")
    (root / "ast2python" / "binder.py").write_text("", encoding="utf-8")
    report = build_release_report(root)
    codes = {item.code for item in report.findings}
    assert {
        "pyproject_version",
        "dependency_pin",
        "public_api_missing",
        "legacy_module_present",
    } <= codes

    import ast2python.release as release_module

    monkeypatch.setattr(release_module, "__version__", "wrong")
    assert any(
        item.code == "wrong_version" for item in release_module.build_release_report(root).findings
    )

    pyproject.unlink()
    assert any(
        item.code == "missing_pyproject"
        for item in release_module.build_release_report(root).findings
    )


def test_release_report_rejects_rc5_compatibility_module(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    shutil.copytree(
        ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage")
    )
    compatibility_module = root / "ast2python" / "openpine_compat.py"
    compatibility_module.write_text("def translate_ast(): ...\n", encoding="utf-8")

    report = build_release_report(root)

    assert any(
        item.code == "legacy_module_present"
        and item.path == "ast2python/openpine_compat.py"
        for item in report.findings
    )


def test_release_report_rejects_rc5_environment_and_export_surfaces(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    shutil.copytree(
        ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage")
    )
    init_path = root / "ast2python" / "__init__.py"
    init_path.write_text(
        init_path.read_text(encoding="utf-8")
        + '\nOPENPINE_RC5_COMPILER_COMPAT = "1"\n'
        + 'translate_ast = object()\n',
        encoding="utf-8",
    )

    report = build_release_report(root)
    surfaces = {
        item.message for item in report.findings if item.code == "legacy_surface_present"
    }

    assert "OPENPINE_RC5_COMPILER_COMPAT" in surfaces
    assert "translate_ast" in surfaces


def test_source_map_docs_use_canonical_schema_id() -> None:
    for relative in ("docs/SOURCE_MAP.md", "docs/COMPATIBILITY.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "openpine.source_map.v2" in text, relative
        assert "ast2python.source_map.v2" not in text, relative


def test_consumer_bundle_regeneration_restores_sys_path_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pine2ast.hardening as producer_hardening

    producer_root = tmp_path / "pine2ast-source"
    source = tmp_path / "source.pine"
    source.write_text("//@version=6\nindicator('x')\n", encoding="utf-8")
    case = RegenerationCase("test", source, source.name, tmp_path / "bundle.json")

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("producer failure")

    monkeypatch.setattr(producer_hardening, "build_consumer_bundle", fail_build)
    original_sys_path = tuple(sys.path)

    with pytest.raises(RuntimeError, match="producer failure"):
        regenerate_cases((case,), producer_root, check=True)

    assert tuple(sys.path) == original_sys_path


def test_cli_non_json_help_and_analysis_session(capsys) -> None:
    path = FIXTURE_ROOT / "pine-v6-consumer-bundle.json"
    assert cli_main(["validate-bundle", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert cli_main(["inspect-bundle", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "ANALYSIS"
    assert cli_main([]) == 2
    assert "usage:" in capsys.readouterr().out

    session = open_compilation_session(load_bundle(6), mode="analysis")
    with pytest.raises(AnalysisOnlyError, match="analysis mode"):
        session.require_runnable_output()
