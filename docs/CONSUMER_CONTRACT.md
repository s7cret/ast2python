# Consumer contract

Production accepts only `pine2ast.consumer_bundle.v1 / 1.0.0` from
`pine2ast==5.0.0rc6`.

Required capabilities:

```text
pine_version_context_v1
pine_ast_v2
pine_semantic_facts_v1
resolved_symbol_identity
resolved_overload_identity
source_span_identity
```

Admission verifies canonical JSON, resource limits, producer identity, source and content
hashes, lineage, exact version context, node index, one-to-one facts, resolved calls,
argument bindings and blocking diagnostics. Plain string input is rejected to avoid
ambiguity between JSON text and filesystem paths.
