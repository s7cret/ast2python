from __future__ import annotations

# Generated signature registry; keep compact for architecture-budget readability.
# fmt: off
from ast2python.binder_model import ParameterSpec, SignatureSpec

TIMEFRAME_SIGNATURES: dict[str, SignatureSpec] = {
    'timeframe.change': SignatureSpec(builtin='timeframe.change', parameters=(ParameterSpec(name='timeframe', accepted_types=frozenset({'object', 'string'}), qualifier_max='series', required=True),), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
}
