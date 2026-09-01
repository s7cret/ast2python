# Security

The compiler rejects duplicate JSON keys, non-finite numbers, oversized/deep documents,
unknown fields, malformed hashes, unsafe module names, unknown target operations,
capability drift and compiler imports in generated modules.

Generated Python is parsed before release and may not call `eval`, `exec`, `compile` or
`__import__`. Source strings remain data inside the IR payload. CLI file admission uses
explicit `Path` objects; archive and package gates separately reject unsafe paths.
