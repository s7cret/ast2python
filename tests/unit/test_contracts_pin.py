from pathlib import Path

from openpine_contracts import SemanticProfile, list_schema_ids, validate_payload

from ast2python.artifact import _digest, build_generated_artifact_v2, resolve_compile_profile
from ast2python.contracts import (
    GENERATED_ARTIFACT_CONTRACT,
    OPENPINE_FRONTEND_CONTRACT_VERSION,
)


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"openpine-contracts==5.0.0rc5"' in text
    assert "openpine-contracts @ git+" not in text
    ids = list_schema_ids()
    assert "openpine.generated_artifact.v2" in ids
    assert "openpine.intent.v2" in ids
    assert OPENPINE_FRONTEND_CONTRACT_VERSION == "openpine.frontend.v2"
    assert GENERATED_ARTIFACT_CONTRACT in ids


def test_new_compile_defaults_to_strict_5x() -> None:
    assert resolve_compile_profile(None) is SemanticProfile.STRICT_5X
    assert resolve_compile_profile(SemanticProfile.LEGACY_4X) is SemanticProfile.LEGACY_4X
    assert _digest(b"artifact", GENERATED_ARTIFACT_CONTRACT) == _digest(
        "artifact", GENERATED_ARTIFACT_CONTRACT
    )


def test_generated_artifact_v2_validates_and_requires_profile() -> None:
    payload = build_generated_artifact_v2(
        source='//@version=6\nindicator("T")\nplot(close)\n',
        ast_payload={"kind": "Program"},
        emitted_module="class GeneratedIndicator:\n    pass\n",
        source_map=[],
        entrypoint_module="generated_indicator",
    )
    validate_payload(GENERATED_ARTIFACT_CONTRACT, payload)
    assert payload["semantic_profile"] == SemanticProfile.STRICT_5X.value
    assert payload["producer"] == "ast2python"
    try:
        resolve_compile_profile("nope")
    except ValueError as exc:
        assert "PL_UNKNOWN_SEMANTIC_PROFILE" in str(exc)
    else:
        raise AssertionError("unknown profile must fail")
