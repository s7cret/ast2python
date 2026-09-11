from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ast2python.admission.ast_view import StrictASTView
from ast2python.admission.canonical import (
    BundleInput,
    enforce_generic_limits,
    freeze_json,
    load_bundle_input,
    thaw_json,
)
from ast2python.admission.facts import SemanticFactsIndex
from ast2python.admission.invariants import (
    PineVersionIdentity,
    validate_bundle_envelope,
    validate_consumer_contract,
    validate_diagnostics,
    validate_source_descriptor,
    validate_version_context,
)
from ast2python.admission.limits import AdmissionLimits
from ast2python.admission.producer_identity import ProducerIdentity, validate_producer_identity
from ast2python.errors import AdmissionFinding, BundleAdmissionError, BundleInvariantError
from ast2python.mode import CompilationMode
from ast2python.version import REQUIRED_PINE2AST_VERSION


@dataclass(frozen=True, slots=True)
class BundleValidationReport:
    ok: bool
    mode: CompilationMode
    findings: tuple[AdmissionFinding, ...]
    pine_version: int | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode.value,
            "pine_version": self.pine_version,
            "content_hash": self.content_hash,
            "findings": [item.to_dict() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class AdmittedConsumerBundle:
    schema_id: str
    schema_version: str
    content_hash: str
    canonical_bytes: bytes
    mode: CompilationMode
    producer: ProducerIdentity
    source: Mapping[str, Any]
    version_context: PineVersionIdentity
    ast: StrictASTView
    semantic_facts: SemanticFactsIndex
    diagnostics: tuple[Mapping[str, Any], ...]
    required_capabilities: frozenset[str]
    linked_artifacts: Mapping[str, Any]
    artifacts: Mapping[str, Any]
    library_context: Mapping[str, Any] | None = None

    @property
    def runnable_output_allowed(self) -> bool:
        return self.mode is CompilationMode.PRODUCTION

    def to_summary(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "mode": self.mode.value,
            "producer": self.producer.to_dict(),
            "source": thaw_json(self.source),
            "version_context": self.version_context.to_dict(),
            "ast": self.ast.to_summary(),
            "semantic_facts": self.semantic_facts.to_summary(),
            "diagnostic_count": len(self.diagnostics),
            "required_capabilities": sorted(self.required_capabilities),
            "linked_artifact_names": sorted(self.linked_artifacts),
            "runnable_output_allowed": self.runnable_output_allowed,
        }


class BundleAdmissionService:
    def __init__(self, *, limits: AdmissionLimits | None = None) -> None:
        self.limits = limits or AdmissionLimits()

    def admit(
        self,
        source: BundleInput,
        *,
        mode: CompilationMode | str = CompilationMode.PRODUCTION,
        expected_producer_commit: str | None = None,
    ) -> AdmittedConsumerBundle:
        normalized_mode = CompilationMode.normalize(mode)
        bundle, canonical_bytes = load_bundle_input(source, self.limits)
        enforce_generic_limits(bundle, self.limits)
        validate_bundle_envelope(bundle, self.limits)

        # The producer owns schema, content-hash and cross-artifact lineage validation.
        # Ast2Python deliberately imports rather than copies this verifier, and admits
        # only the exact coordinated Pine2AST package version.
        try:
            import pine2ast
            from pine2ast.hardening.consumer_bundle import verify_consumer_bundle
        except ImportError as exc:
            raise BundleInvariantError(
                "A2P_PINE2AST_VERIFIER_MISSING",
                f"Pine2AST {REQUIRED_PINE2AST_VERSION} consumer-bundle verifier is unavailable",
            ) from exc
        actual_pine2ast_version = getattr(pine2ast, "__version__", None)
        if actual_pine2ast_version != REQUIRED_PINE2AST_VERSION:
            raise BundleInvariantError(
                "A2P_PINE2AST_VERSION_MISMATCH",
                "installed Pine2AST version does not match the coordinated consumer contract",
                details={
                    "required": REQUIRED_PINE2AST_VERSION,
                    "actual": actual_pine2ast_version,
                },
            )
        try:
            if (bundle["ast"].get("schema_version") == "2.1"
                    or "user_method_function_calls_v1" in bundle.get("consumer_contract", {}).get("required_capabilities", [])):
                try:
                    from pine2ast.ast.decode import ASTReplayLimits
                except ImportError as exc:
                    raise BundleInvariantError(
                        "A2P_RECEIVER_REPLAY_UNAVAILABLE",
                        "AST2.1 requires the producer's closed AST replay API",
                    ) from exc
                defaults = ASTReplayLimits()
                replay_limits = ASTReplayLimits(
                    max_bytes=min(defaults.max_bytes, self.limits.max_bundle_bytes),
                    max_depth=min(defaults.max_depth, self.limits.max_json_depth),
                    max_values=min(defaults.max_values, self.limits.max_total_json_nodes),
                    max_ast_nodes=min(defaults.max_ast_nodes, self.limits.max_ast_nodes),
                    max_container_items=min(
                        defaults.max_container_items, self.limits.max_container_items
                    ),
                    max_string_length=min(
                        defaults.max_string_length, self.limits.max_string_length
                    ),
                )
                verify_consumer_bundle(
                    bundle,
                    expected_producer_commit=expected_producer_commit,
                    ast_replay_limits=replay_limits,
                )
            else:
                # Preserve the actual old producer callable signature for 2.0.
                # No TypeError retry can bypass new-feature verification.
                verify_consumer_bundle(bundle, expected_producer_commit=expected_producer_commit)
        except (ValueError, KeyError, TypeError) as exc:
            raise BundleInvariantError(
                "A2P_PRODUCER_VERIFICATION",
                f"Pine2AST consumer-bundle verification failed: {exc}",
            ) from exc

        producer = validate_producer_identity(bundle["producer"])
        version_context = validate_version_context(bundle["version_context"])
        source_descriptor = validate_source_descriptor(bundle["source"])
        required_capabilities = validate_consumer_contract(
            bundle["consumer_contract"],
            self.limits,
            library_context="library_context" in bundle,
            library_methods=(bundle.get("library_context", {}).get("schema_id") == "pine2ast.library_qualifier_context.v2"),
            method_receiver_qualifiers=bundle["ast"].get("schema_version") == "2.1",
            method_function_calls="user_method_function_calls_v1" in bundle["consumer_contract"]["required_capabilities"],
        )
        diagnostics = validate_diagnostics(bundle["diagnostics"], normalized_mode)
        ast_view = StrictASTView.build(
            bundle["ast"],
            bundle["node_index"],
            version_context=bundle["version_context"],
            method_receiver_qualifiers=bundle["ast"].get("schema_version") == "2.1",
        )
        facts = SemanticFactsIndex.build(
            bundle["semantic_facts"],
            ast_view=ast_view,
            version_context=bundle["version_context"],
            production=normalized_mode is CompilationMode.PRODUCTION,
        )
        return AdmittedConsumerBundle(
            schema_id=str(bundle["schema_id"]),
            schema_version=str(bundle["schema_version"]),
            content_hash=str(bundle["content_hash"]),
            canonical_bytes=canonical_bytes,
            mode=normalized_mode,
            producer=producer,
            source=freeze_json(source_descriptor),
            version_context=version_context,
            ast=ast_view,
            semantic_facts=facts,
            diagnostics=tuple(freeze_json(dict(item)) for item in diagnostics),
            required_capabilities=required_capabilities,
            linked_artifacts=freeze_json(bundle["linked_artifacts"]),
            artifacts=freeze_json(bundle["artifacts"]),
            library_context=(
                freeze_json(bundle["library_context"]) if "library_context" in bundle else None
            ),
        )

    def validate(
        self,
        source: BundleInput,
        *,
        mode: CompilationMode | str = CompilationMode.PRODUCTION,
        expected_producer_commit: str | None = None,
    ) -> BundleValidationReport:
        normalized_mode = CompilationMode.normalize(mode)
        try:
            admitted = self.admit(
                source,
                mode=normalized_mode,
                expected_producer_commit=expected_producer_commit,
            )
        except BundleAdmissionError as exc:
            return BundleValidationReport(
                ok=False,
                mode=normalized_mode,
                findings=(exc.finding,),
            )
        return BundleValidationReport(
            ok=True,
            mode=normalized_mode,
            findings=(),
            pine_version=admitted.version_context.pine_version,
            content_hash=admitted.content_hash,
        )

    def inspect(
        self,
        source: BundleInput,
        *,
        mode: CompilationMode | str = CompilationMode.ANALYSIS,
        expected_producer_commit: str | None = None,
    ) -> dict[str, Any]:
        return self.admit(
            source,
            mode=mode,
            expected_producer_commit=expected_producer_commit,
        ).to_summary()
