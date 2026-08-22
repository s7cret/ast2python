"""Public translation facade and embedded artifact extraction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ast2python.ast.schema import ASTProgram
from ast2python.result import TranslationResult
from ast2python.visuals import VisualPolicy


def translate_ast(
    program: ASTProgram | dict[str, Any],
    *,
    compile_profile: Literal["production", "diagnostic"] = "production",
    strict: bool = False,
    emit_source_comments: bool = True,
    module_name: str | None = None,
    allow_invalid_ast: bool = False,
    allow_contract_mismatch: bool = False,
    allow_external_library_stubs: bool = False,
    allow_unsupported_request_stubs: bool = False,
    allow_realtime_local_simulation: bool = False,
    visual_policy: VisualPolicy | str = "drop",
    source: str | None = None,
    ast_artifact: Mapping[str, Any] | None = None,
    frontend_artifact: Mapping[str, Any] | None = None,
    support_profile: Mapping[str, Any] | None = None,
    producer_commits: Mapping[str, Any] | None = None,
    semantic_profile: object | None = None,
    created_at_utc_ms: int = 0,
) -> TranslationResult:
    from ast2python.translator import Translator

    if isinstance(program, dict):
        if source is None:
            candidate_source = program.get("source") or program.get("source_text")
            source = candidate_source if isinstance(candidate_source, str) else None
        if frontend_artifact is None:
            candidate_frontend = program.get("frontend_artifact") or program.get("frontend")
            frontend_artifact = (
                candidate_frontend if isinstance(candidate_frontend, Mapping) else None
            )
        if ast_artifact is None:
            candidate_ast_artifact = program.get("ast_artifact")
            ast_artifact = (
                candidate_ast_artifact if isinstance(candidate_ast_artifact, Mapping) else None
            )
        if support_profile is None:
            candidate_support = program.get("support_profile")
            support_profile = candidate_support if isinstance(candidate_support, Mapping) else None
    if semantic_profile is None and frontend_artifact is not None:
        semantic_profile = frontend_artifact.get("semantic_profile")
    return Translator(
        compile_profile=compile_profile,
        strict=strict,
        emit_source_comments=emit_source_comments,
        allow_invalid_ast=allow_invalid_ast,
        allow_contract_mismatch=allow_contract_mismatch,
        allow_external_library_stubs=allow_external_library_stubs,
        allow_unsupported_request_stubs=allow_unsupported_request_stubs,
        allow_realtime_local_simulation=allow_realtime_local_simulation,
        visual_policy=visual_policy,
    ).translate_program(
        program,
        module_name=module_name,
        source=source,
        ast_artifact=ast_artifact,
        frontend_artifact=frontend_artifact,
        support_profile=support_profile,
        producer_commits=producer_commits,
        semantic_profile=semantic_profile,
        created_at_utc_ms=created_at_utc_ms,
    )


__all__ = ["translate_ast"]
