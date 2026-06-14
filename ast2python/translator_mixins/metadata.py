"""Compatibility façade for translator metadata helper modules."""

from __future__ import annotations

from ast2python.translator_constants import (
    BUILTIN_SERIES,
    ENUM_DECLARATIONS,
    FUNCTION_DECLARATIONS,
    METHOD_DECLARATIONS,
    STRATEGY_READONLY_FIELDS,
    UDT_DECLARATIONS,
)
from ast2python.translator_mixins.metadata_build import build_metadata
from ast2python.translator_mixins.metadata_declarations import (
    call_arguments as _call_arguments,
)
from ast2python.translator_mixins.metadata_declarations import (
    collect_declaration_metadata,
    extract_declaration_title,
    literal_or_rendered,
    strategy_context_kwargs,
)
from ast2python.translator_mixins.metadata_globals import collect_globals
from ast2python.translator_mixins.metadata_inputs import _default_for_type, build_input_metadata
from ast2python.translator_mixins.metadata_requests import (
    contains_any_request_call,
    contains_request_call,
    diagnose_request_security_captures,
    diagnose_request_security_lower_tf_safety,
    is_lower_tf_safe_immutable_scalar_capture,
)
from ast2python.translator_mixins.metadata_type_info import (
    _type_ref_name,
    infer_dtype,
    infer_type_info,
)
from ast2python.translator_support import member_chain

__all__ = [
    "BUILTIN_SERIES",
    "ENUM_DECLARATIONS",
    "FUNCTION_DECLARATIONS",
    "METHOD_DECLARATIONS",
    "STRATEGY_READONLY_FIELDS",
    "UDT_DECLARATIONS",
    "_call_arguments",
    "_default_for_type",
    "_type_ref_name",
    "build_input_metadata",
    "build_metadata",
    "collect_declaration_metadata",
    "collect_globals",
    "contains_any_request_call",
    "contains_request_call",
    "diagnose_request_security_captures",
    "diagnose_request_security_lower_tf_safety",
    "extract_declaration_title",
    "infer_dtype",
    "infer_type_info",
    "is_lower_tf_safe_immutable_scalar_capture",
    "literal_or_rendered",
    "member_chain",
    "strategy_context_kwargs",
]
