from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn

from ast2python.arg_helper import call_arguments, ordered_call_arguments
from ast2python.ast.schema import ASTNode, ASTProgram, ensure_program_node, load_ast, validate_ast
from ast2python.binder import BUILTIN_SIGNATURES, bind_builtin_call
from ast2python.call_dispatch import dispatch_call
from ast2python.call_registry import CALL_EXACT, CALL_PREFIX
from ast2python.context import TranslationContext, VariableInfo
from ast2python.contracts import (
    AST_CONTRACT_VERSION,
    ast_contract_is_current,
    runtime_contract_is_compatible,
)
from ast2python.diagnostics import (
    BINDER_SIGNATURE_MISMATCH,
    BINDER_UNSUPPORTED_BUILTIN,
    BOOL_NA_OVERLOAD,
    CALC_ON_EVERY_TICK_UNSAFE,
    CONTRACT_VERSION_MISMATCH,
    EXTERNAL_LIBRARY_CALL,
    NESTED_REQUEST_SECURITY,
    REFERENCE_COPY_POLICY,
    REFERENCE_HISTORY_UNSUPPORTED,
    REQUEST_SECURITY_CAPTURE_UNSAFE,
    UNKNOWN_OVERLOAD,
    UNSUPPORTED_NODE,
    UNSUPPORTED_REQUEST,
    VARIP_UNSAFE,
    VISUAL_CALL_DROPPED,
    VISUAL_CALL_FORBIDDEN,
    VISUAL_FRONTEND_DIAGNOSTIC_IGNORED,
    VISUAL_OBJECT_USED_AS_VALUE,
    WARNING_NESTED_SECURITY,
    Severity,
)
from ast2python.emitter import CodeEmitter
from ast2python.emitters.alerts import PineAlertEmitter
from ast2python.emitters.inputs import PineInputEmitter
from ast2python.emitters.time import PineTimeEmitter
from ast2python.errors import (
    ScopeResolutionError,
    TypeResolutionError,
    UnsupportedBuiltinError,
    UnsupportedNodeError,
    ValidationError,
)
from ast2python.naming import snake_case
from ast2python.profiles import CompileProfile
from ast2python.result import TranslationResult
from ast2python.state import state_id_for_call, state_id_py_expr
from ast2python.switch_helper import case_body, case_condition, switch_cases
from ast2python.templates.module import base_class_for_mode, class_name_for_mode
from ast2python.translator_constants import (
    ATR_SHORTHANDS,
    BUILTIN_SERIES,
    DECLARATION_CONTEXT_FIELDS,
    DERIVED_BUILTIN_SERIES,
    ENUM_DECLARATIONS,
    FUNCTION_DECLARATIONS,
    LOWER_TF_IMMUTABLE_SCALAR_BASE_TYPES,
    LOWER_TF_PURE_CALL_PREFIXES,
    METHOD_DECLARATIONS,
    STATEFUL_TA_FUNCTIONS,
    STRATEGY_CALLS_P0,
    STRATEGY_CONTEXT_FIELDS,
    STRATEGY_READONLY_FIELDS,
    TIME_COMPONENT_BUILTINS,
    UDT_DECLARATIONS,
    VISUAL_OBJECT_METHOD_PREFIXES,
)
from ast2python.translator_mixins.metadata import (
    build_metadata,
    collect_declaration_metadata,
    collect_globals,
    contains_any_request_call,
    contains_request_call,
    extract_declaration_title,
    literal_or_rendered,
    strategy_context_kwargs,
)
from ast2python.translator_mixins.type_inference import infer_type_info
from ast2python.translator_support import literal_value, member_chain
from ast2python.types import TypeInfo, make_type_info
from ast2python.version import RUNTIME_CONTRACT_VERSION
from ast2python.visuals import frontend_diagnostic_visual_call, visual_call_from_call_chain

if TYPE_CHECKING:
    from ast2python.translator_protocols import TranslatorMixinProtocol as TranslatorMixinBase
else:

    class TranslatorMixinBase:
        pass
