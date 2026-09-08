"""The new producer keyword is negotiated only for the new AST feature."""

import pytest
from pine2ast.hardening import consumer_bundle as producer

from ast2python.admission import BundleAdmissionService
from ast2python.admission.limits import AdmissionLimits
from ast2python.errors import BundleInvariantError


def bundle(*, feature):
    qualifier = "simple " if feature else ""
    return producer.build_consumer_bundle(
        f'//@version=6\nindicator("API compatibility")\nmethod add({qualifier}int self)=>self+1\na=2\nplot(a.add())\n'
    )


def test_ast20_keeps_the_genuine_old_verifier_keyword_signature(monkeypatch):
    payload = bundle(feature=False)
    original = producer.verify_consumer_bundle
    observed = []

    # Exact old public signature: it does not accept ast_replay_limits or **kwargs.
    def old_verifier(payload, *, source=None, expected_producer_commit=None):
        observed.append(expected_producer_commit)
        return original(payload, source=source, expected_producer_commit=expected_producer_commit)

    monkeypatch.setattr(producer, "verify_consumer_bundle", old_verifier)
    admitted = BundleAdmissionService().admit(payload)
    assert admitted.ast.nodes[admitted.ast.root_node_id].fields["schema_version"] == "2.0"
    assert observed == [None]


def test_ast21_passes_exact_bounded_limits_to_the_producer_owner(monkeypatch):
    payload = bundle(feature=True)
    original = producer.verify_consumer_bundle
    observed = []

    def new_verifier(payload, *, expected_producer_commit=None, ast_replay_limits):
        observed.append(ast_replay_limits)
        return original(
            payload,
            expected_producer_commit=expected_producer_commit,
            ast_replay_limits=ast_replay_limits,
        )

    monkeypatch.setattr(producer, "verify_consumer_bundle", new_verifier)
    admitted = BundleAdmissionService(
        limits=AdmissionLimits(max_json_depth=100, max_ast_nodes=10000)
    ).admit(payload)
    assert admitted.ast.nodes[admitted.ast.root_node_id].fields["schema_version"] == "2.1"
    assert len(observed) == 1
    assert observed[0].max_depth == 100
    assert observed[0].max_ast_nodes == 10000


def test_ast21_verifier_typeerror_never_triggers_an_old_signature_retry(monkeypatch):
    payload = bundle(feature=True)
    calls = []

    def broken(payload, *, expected_producer_commit=None, ast_replay_limits):
        calls.append(ast_replay_limits)
        raise TypeError("deliberate new verifier failure")

    monkeypatch.setattr(producer, "verify_consumer_bundle", broken)
    with pytest.raises(BundleInvariantError, match="deliberate new verifier failure"):
        BundleAdmissionService().admit(payload)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,maximum",
    [("max_json_depth", 256), ("max_ast_nodes", 2000000), ("max_bundle_bytes", 67108864)],
)
def test_consumer_larger_local_limits_do_not_expand_producer_absolute_replay_profile(
    monkeypatch, field, maximum
):
    from pine2ast.ast.decode import ASTReplayLimits

    payload = bundle(feature=True)
    original = producer.verify_consumer_bundle
    observed = []

    def checked(payload, *, expected_producer_commit=None, ast_replay_limits):
        observed.append(ast_replay_limits)
        return original(
            payload,
            expected_producer_commit=expected_producer_commit,
            ast_replay_limits=ast_replay_limits,
        )

    monkeypatch.setattr(producer, "verify_consumer_bundle", checked)
    BundleAdmissionService(limits=AdmissionLimits(**{field: maximum})).admit(payload)
    assert observed == [ASTReplayLimits()]
