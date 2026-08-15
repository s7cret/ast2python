from ast2python.generated_artifact_v2 import (
    GENERATED_ARTIFACT_V2,
    GeneratedArtifactError,
    build_generated_artifact_v2,
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
