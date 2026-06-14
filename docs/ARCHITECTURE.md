# Architecture

AST2Python is a lowering and code-generation package. Its input is a Pine AST JSON envelope; its output is Python code plus metadata, diagnostics, source maps and coverage information.

## Main layers

```text
ast/schema.py            AST envelope loading and validation
translator.py            thin public Translator facade
translator_parts/        module, statement, declaration, expression, call and metadata lowering
binder.py                builtin binding algorithm
binder_signatures/       namespace-specific builtin signature tables
emitters/                focused Python emitter helpers
runtime_contract/        abstract runtime contract surface
cli/                     parser and command dispatch
lowering_matrix/         documented lowering support matrix
```

The 4.0 refactor keeps the public `Translator` and `translate_ast()` API stable while removing the previous single-file translator bottleneck.

## Boundary

AST2Python does not try to interpret Pine bars or simulate TradingView. It generates PineLib-targeted Python modules and fail-closes where static lowering cannot preserve parity safely.
