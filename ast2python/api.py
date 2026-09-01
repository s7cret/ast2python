from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ast2python.compiler import CompilationResult

from ast2python.admission import (
    AdmissionLimits,
    AdmittedConsumerBundle,
    BundleAdmissionService,
    BundleValidationReport,
)
from ast2python.admission.canonical import BundleInput
from ast2python.mode import CompilationMode
from ast2python.session import CompilationSession


def validate_consumer_bundle(
    source: BundleInput,
    *,
    limits: AdmissionLimits | None = None,
    mode: CompilationMode | str = CompilationMode.PRODUCTION,
    expected_producer_commit: str | None = None,
) -> BundleValidationReport:
    return BundleAdmissionService(limits=limits).validate(
        source,
        mode=mode,
        expected_producer_commit=expected_producer_commit,
    )


def admit_consumer_bundle(
    source: BundleInput,
    *,
    limits: AdmissionLimits | None = None,
    mode: CompilationMode | str = CompilationMode.PRODUCTION,
    expected_producer_commit: str | None = None,
) -> AdmittedConsumerBundle:
    return BundleAdmissionService(limits=limits).admit(
        source,
        mode=mode,
        expected_producer_commit=expected_producer_commit,
    )


def inspect_consumer_bundle(
    source: BundleInput,
    *,
    limits: AdmissionLimits | None = None,
    expected_producer_commit: str | None = None,
) -> dict[str, Any]:
    return BundleAdmissionService(limits=limits).inspect(
        source,
        mode=CompilationMode.ANALYSIS,
        expected_producer_commit=expected_producer_commit,
    )


def open_compilation_session(
    source: BundleInput,
    *,
    limits: AdmissionLimits | None = None,
    mode: CompilationMode | str = CompilationMode.PRODUCTION,
    expected_producer_commit: str | None = None,
) -> CompilationSession:
    return CompilationSession(
        admit_consumer_bundle(
            source,
            limits=limits,
            mode=mode,
            expected_producer_commit=expected_producer_commit,
        )
    )


def compile_consumer_bundle(*args: Any, **kwargs: Any) -> CompilationResult:
    from ast2python.compiler import compile_consumer_bundle as compile_impl

    return compile_impl(*args, **kwargs)


__all__ = [
    "admit_consumer_bundle",
    "compile_consumer_bundle",
    "inspect_consumer_bundle",
    "open_compilation_session",
    "validate_consumer_bundle",
]
