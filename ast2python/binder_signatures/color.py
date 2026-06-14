from __future__ import annotations

# Generated signature registry; keep compact for architecture-budget readability.
# fmt: off
from ast2python.binder_model import ParameterSpec, SignatureSpec

COLOR_SIGNATURES: dict[str, SignatureSpec] = {
    'color.new': SignatureSpec(builtin='color.new', parameters=(ParameterSpec(name='color', accepted_types=frozenset({'color', 'object', 'array', 'map', 'bool', 'any', 'string', 'int', 'float', 'PineObjectId', 'matrix'}), qualifier_max='series', required=True), ParameterSpec(name='transp', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
}
