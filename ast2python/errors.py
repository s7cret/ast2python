class AST2PythonError(Exception):
    """Base AST2Python error."""


class RuntimeContractError(AST2PythonError):
    """Generated/runtime contract mismatch."""


class ValidationError(AST2PythonError):
    """AST validation failure."""


class UnsupportedNodeError(AST2PythonError):
    """Unsupported AST node."""


class UnsupportedBuiltinError(AST2PythonError):
    """Unsupported builtin call or member."""


class TypeResolutionError(AST2PythonError):
    """Type/overload resolution failure."""


class ScopeResolutionError(AST2PythonError):
    """Variable scope resolution failure."""


class NameCollisionError(AST2PythonError):
    """Unable to allocate a unique Python name."""


class CodegenError(AST2PythonError):
    """General code generation failure."""


class SourceMapError(AST2PythonError):
    """Invalid source map operation."""
