from ast2python.generated_artifact_v2 import (
    DEFAULT_IMPORT_ALLOWLIST,
    GENERATED_ARTIFACT_V2,
    GeneratedArtifactError,
    build_generated_artifact_v2,
    extract_import_allowlist,
    resolve_semantic_profile,
)


def test_generated_artifact_v2_defaults_to_strict_5x() -> None:
    payload = build_generated_artifact_v2(code="from pinelib.core import na\n")
    assert payload["schema_id"] == GENERATED_ARTIFACT_V2
    assert payload["semantic_profile"] == "strict_5x"
    assert "pinelib.core" in payload["import_allowlist"]
    assert payload["emitted_module_hash"].startswith("sha256:")


def test_unknown_semantic_profile_fail_closed() -> None:
    try:
        resolve_semantic_profile("maybe")
    except GeneratedArtifactError as exc:
        assert exc.code == "UNKNOWN_SEMANTIC_PROFILE"
    else:
        raise AssertionError("unknown profile must fail")


def test_extract_import_allowlist_reads_import_and_from_lines() -> None:
    names = extract_import_allowlist(
        "import pinelib.strategy\nfrom pinelib.core import na\nimport json\n"
    )
    assert names == ("pinelib", "pinelib.core")


def test_extract_import_allowlist_falls_back_when_no_pinelib() -> None:
    assert extract_import_allowlist("import json\n") == DEFAULT_IMPORT_ALLOWLIST


def test_generated_artifact_v2_records_source_map_and_capabilities() -> None:
    payload = build_generated_artifact_v2(
        code="from pinelib.ta import sma\n",
        source_map=[{"node": "sma", "line": 1}],
        frontend_hash="sha256:abc",
        semantic_profile="legacy_4x",
        required_runtime_capabilities=("intent_tape", "mtf"),
    )
    assert payload["semantic_profile"] == "legacy_4x"
    assert payload["source_hash"] == "sha256:abc"
    assert payload["required_runtime_capabilities"] == ["intent_tape", "mtf"]
    assert payload["import_allowlist"] == ["pinelib.ta"]
    assert payload["source_map_hash"].startswith("sha256:")
