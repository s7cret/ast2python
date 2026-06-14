from __future__ import annotations

# Generated signature registry; keep compact for architecture-budget readability.
# fmt: off
from ast2python.binder_model import ParameterSpec, SignatureSpec

LINE_SIGNATURES: dict[str, SignatureSpec] = {
    'line.delete': SignatureSpec(builtin='line.delete', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True),), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
    'line.new': SignatureSpec(builtin='line.new', parameters=(ParameterSpec(name='x1', accepted_types=frozenset({'int'}), qualifier_max='series', required=True), ParameterSpec(name='y1', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True), ParameterSpec(name='x2', accepted_types=frozenset({'int'}), qualifier_max='series', required=True), ParameterSpec(name='y2', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset({'color', 'style', 'xloc', 'extend', 'width', 'force_overlay'}), codegen_supported=True, notes=''),
    'line.set_xy1': SignatureSpec(builtin='line.set_xy1', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='x', accepted_types=frozenset({'int'}), qualifier_max='series', required=True), ParameterSpec(name='y', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
    'line.set_xy2': SignatureSpec(builtin='line.set_xy2', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='x', accepted_types=frozenset({'int'}), qualifier_max='series', required=True), ParameterSpec(name='y', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
}
