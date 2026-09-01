# Lowering IR

`ast2python.lowering_plan.v1` is immutable and hash-bound. It contains:

- bundle, version-context, catalog and target identities;
- deterministic IR order and root identity;
- exact source node and span for every IR node;
- operation, effect and evaluation policy;
- resolved type/qualifier/nullability;
- child identities;
- symbol, overload, call-form and semantic-rule facts;
- required target operations and capabilities.

Recipes are selected from exact producer facts and Pine version. Unknown AST kinds,
missing call facts, absent operations and target-policy mismatches fail before emission.
