from __future__ import annotations

# Generated signature registry; keep compact for architecture-budget readability.
# fmt: off
from ast2python.binder_model import ParameterSpec, SignatureSpec

TABLE_SIGNATURES: dict[str, SignatureSpec] = {
    'table.cell': SignatureSpec(builtin='table.cell', parameters=(ParameterSpec(name='table_id', accepted_types=frozenset({'PineObjectId', 'line', 'table', 'box', 'label'}), qualifier_max='series', required=True), ParameterSpec(name='column', accepted_types=frozenset({'int'}), qualifier_max='simple', required=True), ParameterSpec(name='row', accepted_types=frozenset({'int'}), qualifier_max='simple', required=True), ParameterSpec(name='text', accepted_types=frozenset({'color', 'object', 'array', 'map', 'bool', 'any', 'string', 'int', 'float', 'PineObjectId', 'matrix'}), qualifier_max='series', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset({'width', 'text_size', 'bgcolor', 'height', 'text_valign', 'tooltip', 'text_color', 'text_halign'}), codegen_supported=True, notes=''),
    'table.new': SignatureSpec(builtin='table.new', parameters=(ParameterSpec(name='position', accepted_types=frozenset({'string'}), qualifier_max='simple', required=True), ParameterSpec(name='columns', accepted_types=frozenset({'int'}), qualifier_max='simple', required=True), ParameterSpec(name='rows', accepted_types=frozenset({'int'}), qualifier_max='simple', required=True)), min_varargs=0, vararg=None, allow_extra_named=frozenset({'frame_width', 'border_color', 'force_overlay', 'border_width', 'bgcolor', 'frame_color'}), codegen_supported=True, notes=''),
}
