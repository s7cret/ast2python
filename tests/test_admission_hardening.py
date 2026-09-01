from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ast2python import AdmissionLimits, admit_consumer_bundle
from ast2python.admission.ast_view import StrictASTView
from ast2python.admission.canonical import enforce_generic_limits, load_bundle_input
from ast2python.admission.facts import SemanticFactsIndex
from ast2python.admission.limits import ABSOLUTE_LIMITS
from ast2python.errors import BundleAdmissionError
from tests.conftest import load_bundle


def _semantic_inputs() -> tuple[dict[str, Any], StrictASTView, dict[str, Any]]:
    bundle_path = Path(__file__).parent / "corpus/v4/v4-unified-input.bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    ast_view = StrictASTView.build(
        bundle["ast"],
        bundle["node_index"],
        version_context=bundle["version_context"],
    )
    return bundle["semantic_facts"], ast_view, bundle["version_context"]


def _assert_semantic_error(
    code: str, mutate: Callable[[dict[str, Any], StrictASTView], None]
) -> None:
    payload, ast_view, version_context = _semantic_inputs()
    invalid = deepcopy(payload)
    mutate(invalid, ast_view)
    with pytest.raises(BundleAdmissionError) as caught:
        SemanticFactsIndex.build(
            invalid,
            ast_view=ast_view,
            version_context=version_context,
            production=True,
        )
    assert caught.value.finding.code == code


@pytest.mark.parametrize("parameter_name", [None, ""])
def test_call_argument_rejects_missing_parameter_name(parameter_name: object) -> None:
    _assert_semantic_error(
        "A2P_CALL_PARAMETER_NAME",
        lambda payload, _ast: payload["calls"][0]["arguments"][0].__setitem__(
            "parameter_name", parameter_name
        ),
    )


@pytest.mark.parametrize("binding", ["GARBAGE", None, []])
def test_call_argument_rejects_unknown_binding(binding: object) -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_BINDING",
        lambda payload, _ast: payload["calls"][0]["arguments"][0].__setitem__("binding", binding),
    )


def test_call_argument_rejects_program_node() -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_KIND",
        lambda payload, ast: payload["calls"][0]["arguments"][0].__setitem__(
            "argument_node_id", ast.root_node_id
        ),
    )


def test_call_argument_must_be_direct_child_of_its_call() -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_CHILD",
        lambda payload, _ast: payload["calls"][0]["arguments"][0].__setitem__(
            "argument_node_id", payload["calls"][1]["arguments"][0]["argument_node_id"]
        ),
    )


def test_call_argument_rejects_duplicate_parameter_index() -> None:
    _assert_semantic_error(
        "A2P_CALL_PARAMETER_INDEX_DUPLICATE",
        lambda payload, _ast: payload["calls"][1]["arguments"][1].__setitem__(
            "parameter_index", payload["calls"][1]["arguments"][0]["parameter_index"]
        ),
    )


def test_call_argument_rejects_duplicate_parameter_name() -> None:
    _assert_semantic_error(
        "A2P_CALL_PARAMETER_NAME_DUPLICATE",
        lambda payload, _ast: payload["calls"][1]["arguments"][1].__setitem__(
            "parameter_name", payload["calls"][1]["arguments"][0]["parameter_name"]
        ),
    )


def test_call_argument_rejects_duplicate_argument_node() -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_NODE_DUPLICATE",
        lambda payload, _ast: payload["calls"][1]["arguments"][1].__setitem__(
            "argument_node_id", payload["calls"][1]["arguments"][0]["argument_node_id"]
        ),
    )


def test_call_argument_requires_complete_argument_child_coverage() -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_COVERAGE",
        lambda payload, _ast: payload["calls"][1]["arguments"].pop(),
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("actual_type", None, "A2P_CALL_ACTUAL_TYPE"),
        ("actual_type", "", "A2P_CALL_ACTUAL_TYPE"),
        ("actual_qualifier", None, "A2P_CALL_ACTUAL_QUALIFIER"),
        ("actual_qualifier", "", "A2P_CALL_ACTUAL_QUALIFIER"),
        ("actual_qualifier", "GARBAGE", "A2P_CALL_ACTUAL_QUALIFIER"),
        ("actual_qualifier", [], "A2P_CALL_ACTUAL_QUALIFIER"),
    ],
)
def test_call_argument_rejects_invalid_actual_type_metadata(
    field: str, value: object, code: str
) -> None:
    _assert_semantic_error(
        code,
        lambda payload, _ast: payload["calls"][0]["arguments"][0].__setitem__(field, value),
    )


def test_named_binding_rejects_positional_ast_argument() -> None:
    _assert_semantic_error(
        "A2P_CALL_ARGUMENT_FORM",
        lambda payload, _ast: payload["calls"][0]["arguments"][0].__setitem__("binding", "named"),
    )


def test_generic_limit_counts_mappings_lists_and_scalars() -> None:
    value = {"items": [1, None]}
    enforce_generic_limits(value, AdmissionLimits(max_total_json_nodes=4))
    with pytest.raises(BundleAdmissionError) as caught:
        enforce_generic_limits(value, AdmissionLimits(max_total_json_nodes=3))
    assert caught.value.finding.code == "A2P_JSON_NODE_LIMIT"


@pytest.mark.parametrize("value", [{"a": 1, "b": 2}, [1, 2]])
def test_generic_limit_rejects_oversized_containers(value: Any) -> None:
    with pytest.raises(BundleAdmissionError) as caught:
        enforce_generic_limits(value, AdmissionLimits(max_container_items=1))
    assert caught.value.finding.code == "A2P_CONTAINER_ITEM_LIMIT"


def test_new_generic_limits_have_absolute_ceilings() -> None:
    with pytest.raises(BundleAdmissionError, match="A2P_LIMIT_ABOVE_ABSOLUTE"):
        AdmissionLimits(max_total_json_nodes=ABSOLUTE_LIMITS.max_total_json_nodes + 1)
    with pytest.raises(BundleAdmissionError, match="A2P_LIMIT_ABOVE_ABSOLUTE"):
        AdmissionLimits(max_container_items=ABSOLUTE_LIMITS.max_container_items + 1)


def test_default_limits_reject_audited_half_million_item_padding() -> None:
    with pytest.raises(BundleAdmissionError) as caught:
        enforce_generic_limits([None] * 500_000, AdmissionLimits())
    assert caught.value.finding.code == "A2P_CONTAINER_ITEM_LIMIT"


@pytest.mark.parametrize("target", ["producer_metadata", "artifacts"])
def test_oversized_metadata_list_fails_before_producer_verifier(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pine2ast.hardening.consumer_bundle as producer_bundle

    verifier_called = False

    def recording_verifier(_bundle: dict[str, Any]) -> None:
        nonlocal verifier_called
        verifier_called = True

    monkeypatch.setattr(producer_bundle, "verify_consumer_bundle", recording_verifier)
    bundle = load_bundle(6)
    container = (
        bundle["ast"]["producer_metadata"] if target == "producer_metadata" else bundle["artifacts"]
    )
    container["oversized"] = [None] * 26

    with pytest.raises(BundleAdmissionError) as caught:
        admit_consumer_bundle(bundle, limits=AdmissionLimits(max_container_items=25))

    assert caught.value.finding.code == "A2P_CONTAINER_ITEM_LIMIT"
    assert verifier_called is False


@pytest.mark.parametrize(
    "source",
    [b'{"integer":' + b"1" * 5_000 + b"}", {"integer": 10**5_000}],
)
def test_huge_integer_failures_have_stable_limit_error(source: Any) -> None:
    with pytest.raises(BundleAdmissionError) as caught:
        load_bundle_input(source, AdmissionLimits())
    assert caught.value.finding.code == "A2P_JSON_INTEGER_LIMIT"


@pytest.mark.parametrize("source", [b'{"text":"\\ud800"}', {"text": "\ud800"}])
def test_lone_surrogate_failures_have_stable_source_error(source: Any) -> None:
    with pytest.raises(BundleAdmissionError) as caught:
        load_bundle_input(source, AdmissionLimits())
    assert caught.value.finding.code == "A2P_JSON_ENCODING"


def test_path_input_rejects_symlink_before_read(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    symlink = tmp_path / "bundle.json"
    symlink.symlink_to(target)

    with pytest.raises(BundleAdmissionError) as caught:
        load_bundle_input(symlink, AdmissionLimits())

    assert caught.value.finding.code == "A2P_BUNDLE_PATH_SYMLINK"


def test_path_input_rejects_non_regular_file_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_attempted = False

    def recording_read(_path: Path) -> bytes:
        nonlocal read_attempted
        read_attempted = True
        return b"{}"

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(BundleAdmissionError) as caught:
        load_bundle_input(tmp_path, AdmissionLimits())

    assert caught.value.finding.code == "A2P_BUNDLE_PATH"
    assert read_attempted is False


def test_path_input_rechecks_actual_bytes_after_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bundle.json"
    path.write_bytes(b"{}")
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"x" * 9)

    with pytest.raises(BundleAdmissionError) as caught:
        load_bundle_input(path, AdmissionLimits(max_bundle_bytes=8))

    assert caught.value.finding.code == "A2P_BUNDLE_TOO_LARGE"
