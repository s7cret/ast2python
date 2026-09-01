# Target ABI

`ast2python.target_manifest.v1` declares the exact operation vocabulary, evaluation mode,
effect class, required capabilities and allowed imports of a runtime target.

A LoweringPlan is accepted only when every used operation exists and its effect/evaluation
policy matches. A generated module repeats the admitted target hash and validates it at
runtime startup.

The repository includes `reference_target_v1.json` solely for compiler validation and
structural smoke tests. Its release status is
`REFERENCE_ONLY_PENDING_PINELIB_RC6`; it must not be represented as a PineLib RC6 target.
