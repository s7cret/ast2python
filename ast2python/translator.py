from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ast2python.ast.schema import ASTProgram, ensure_program_node, load_ast, validate_ast
from ast2python.context import TranslationContext, VariableInfo
from ast2python.emitter import CodeEmitter
from ast2python.emitters.alerts import PineAlertEmitter
from ast2python.emitters.inputs import PineInputEmitter
from ast2python.emitters.time import PineTimeEmitter
from ast2python.errors import ValidationError
from ast2python.profiles import CompileProfile
from ast2python.result import TranslationResult
from ast2python.translator_parts.calls import TranslatorCallMixin
from ast2python.translator_parts.declarations import TranslatorDeclarationMixin
from ast2python.translator_parts.expressions import TranslatorExpressionMixin
from ast2python.translator_parts.metadata import TranslatorMetadataMixin
from ast2python.translator_parts.module import TranslatorModuleMixin
from ast2python.translator_parts.statements import TranslatorStatementMixin
from ast2python.translator_parts.validation import TranslatorValidationMixin
from ast2python.translator_support import member_chain
from ast2python.visuals import VisualPolicy, normalize_visual_policy


class Translator(
    TranslatorValidationMixin,
    TranslatorModuleMixin,
    TranslatorStatementMixin,
    TranslatorDeclarationMixin,
    TranslatorExpressionMixin,
    TranslatorCallMixin,
    TranslatorMetadataMixin,
):
    TUPLE_RETURNING_BUILTINS = {
        "ta.bb": ("float", "float", "float"),
        "ta.macd": ("float", "float", "float"),
        "ta.supertrend": ("float", "int"),
    }

    def __init__(
        self,
        *,
        compile_profile: Literal["production", "diagnostic"] = "production",
        strict: bool = False,
        emit_source_comments: bool = True,
        allow_invalid_ast: bool = False,
        allow_contract_mismatch: bool = False,
        allow_external_library_stubs: bool = False,
        allow_unsupported_request_stubs: bool = False,
        allow_realtime_local_simulation: bool = False,
        visual_policy: VisualPolicy | str = "drop",
    ) -> None:
        try:
            profile = CompileProfile.from_options(
                compile_profile,
                allow_external_library_stubs=allow_external_library_stubs,
                allow_unsupported_request_stubs=allow_unsupported_request_stubs,
                allow_invalid_ast=allow_invalid_ast
                or allow_contract_mismatch
                or allow_realtime_local_simulation,
            )
        except ValueError as exc:
            if str(exc) != "production compile profile forbids unsafe overrides":
                raise ValidationError(str(exc)) from exc
            unsafe_flags = {
                "allow_invalid_ast": allow_invalid_ast,
                "allow_contract_mismatch": allow_contract_mismatch,
                "allow_external_library_stubs": allow_external_library_stubs,
                "allow_unsupported_request_stubs": allow_unsupported_request_stubs,
                "allow_realtime_local_simulation": allow_realtime_local_simulation,
            }
            enabled_unsafe_flags = sorted(name for name, enabled in unsafe_flags.items() if enabled)
            raise ValidationError(
                "production compile profile forbids unsafe overrides: "
                + ", ".join(enabled_unsafe_flags)
            ) from exc
        self.profile = profile
        self.compile_profile = profile.name
        self.strict = strict
        self.emit_source_comments = emit_source_comments
        self.allow_invalid_ast = profile.allow_invalid_ast and allow_invalid_ast
        self.allow_contract_mismatch = profile.allow_invalid_ast and allow_contract_mismatch
        self.allow_external_library_stubs = profile.allow_external_library_stubs
        self.allow_unsupported_request_stubs = profile.allow_unsupported_request_stubs
        self.allow_realtime_local_simulation = (
            profile.allow_invalid_ast and allow_realtime_local_simulation
        )
        self.visual_policy = normalize_visual_policy(visual_policy)
        self.parity_safe = True
        self.unsupported_features: set[str] = set()
        self.parity_risks: list[str] = []
        self.ctx = TranslationContext(strict=strict)
        self.emitter = CodeEmitter(self.ctx.source_map, emit_source_comments=emit_source_comments)
        self.member_chain = member_chain
        # Per-translation state tracking which var-declaration pine names have
        # been emitted at least once; used to give `var x := rhs` reassign the
        # Pine one-bar-deferred read semantics.
        self._var_init_emitted: set[str] = set()
        self.alert_emitter = PineAlertEmitter(self)
        self.input_emitter = PineInputEmitter(self)
        self.time_emitter = PineTimeEmitter(self)
        self.global_series: list[tuple[VariableInfo, str]] = []
        self.input_series: list[tuple[VariableInfo, str, dict[str, Any]]] = []
        self.var_flags: list[VariableInfo] = []
        self.functions: set[str] = set()
        self.methods: set[str] = set()
        self._temp_series_index: int = 0
        self._lazy_branch_depth: int = 0

    def translate_file(
        self, path: str | Path, *, module_name: str | None = None
    ) -> TranslationResult:
        return self.translate_program(load_ast(path), module_name=module_name or Path(path).stem)

    def translate_program(
        self, program: ASTProgram | dict[str, Any], *, module_name: str | None = None
    ) -> TranslationResult:
        if isinstance(program, dict):
            program = ensure_program_node(program)
        # Reset per-translation state that lives on the Translator instance.
        self._var_init_emitted = set()
        problems = validate_ast(program)
        if problems:
            raise ValidationError("; ".join(problems))
        self._enforce_frontend_contract(program)
        for _ in program.descendants():
            self.ctx.coverage.seen()
        declaration = program.declaration
        if declaration is None:
            raise ValidationError("Program declaration is required")
        mode = declaration.field("script_type", default="indicator")
        self.ctx.mode = str(mode)
        title = self._extract_declaration_title(declaration)
        self._enforce_realtime_boundary(declaration)
        self._enforce_varip_boundary(program)
        if self.ctx.mode != "strategy":
            self._collect_declaration_metadata(declaration)
        result_module_name = module_name or self.ctx.naming.reserve(title or "generated")
        self._emit_module(program, declaration, title=title, module_name=result_module_name)
        metadata = self._build_metadata(program, title=title, module_name=result_module_name)
        coverage = self.ctx.coverage.to_dict()
        coverage.update(self._source_map_line_coverage(program))
        return TranslationResult(
            code=self.emitter.render(),
            metadata=metadata,
            source_map=self.ctx.source_map.to_list(),
            coverage=coverage,
            diagnostics=self.ctx.diagnostics,
            module_name=result_module_name,
        )


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
) -> TranslationResult:
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
    )
