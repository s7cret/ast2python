from __future__ import annotations

# Generated signature registry; keep compact for architecture-budget readability.
# fmt: off
from ast2python.binder_model import ParameterSpec, SignatureSpec

LABEL_SIGNATURES: dict[str, SignatureSpec] = {
    'label.delete': SignatureSpec(builtin='label.delete', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True),), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
    'label.new': SignatureSpec(builtin='label.new', parameters=(ParameterSpec(name='x', accepted_types=frozenset({'int'}), qualifier_max='series', required=True), ParameterSpec(name='y', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True), ParameterSpec(name='text', accepted_types=frozenset({'string'}), qualifier_max='series', required=False)), min_varargs=0, vararg=None, allow_extra_named=frozenset({'textcolor', 'color', 'style', 'yloc', 'xloc', 'size', 'tooltip', 'textalign', 'force_overlay'}), codegen_supported=True, notes=''),
    'label.set_color': SignatureSpec(builtin='label.set_color', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='color', accepted_types=frozenset({'string'}), qualifier_max='simple', required=False)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
    'label.set_text': SignatureSpec(builtin='label.set_text', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='text', accepted_types=frozenset({'string'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
    'label.set_y': SignatureSpec(builtin='label.set_y', parameters=(ParameterSpec(name='id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='y', accepted_types=frozenset({'int', 'float', 'source'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset(), codegen_supported=True, notes=''),
}
