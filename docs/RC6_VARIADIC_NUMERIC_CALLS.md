# RC6 canonical variadic calls

Modern `math.min` and `math.max` can pass every positional operand through the
producer, compiler and runtime. Previously a repeated canonical parameter index
was rejected or a target mapping attempted to pass the entire group as a keyword.

Admission obtains the exact canonical signature from the producer catalog whose
hash matches the admitted version context. It permits repeated parameter identity
only for that signature's single final variadic group. Each operand retains its
AST argument identity and source order, declared parameter type and qualifier
ceiling, and independently admitted value-child type and qualifier. Scalar calls
cannot acquire variadic behavior by relabeling facts.

The target uses an explicit `SOURCE_VARIADIC` binding to an inspected
`VAR_POSITIONAL` ABI parameter. The current profile rejects a fixed positional
prefix and `**kwargs`; it does not infer spread from a parameter name. Emission
retains all group values in source order and evaluates each once. Ordinary
`SOURCE_PARAMETER` mappings keep their established behavior.

This change requires coordinated producer and runtime pins. It introduces no
catalog names, version availability, semantic-owner fallback, or schema version.
Only the runtime's reviewed modern min/max rows activate the new target binding.

The 82 added tests cover independently written finite min/max results in Pine 5
and 6, nested series calls through historical/realtime/abort retry/checkpoint
execution, side-effect order, forged facts, and malformed ABI bindings. All 1,028
existing compiler tests remain. Local full runs on Python 3.11 and 3.13 each have
1,109 passes and the same Windows symlink-privilege failure. Strict mypy comparison
retains all 447 baseline diagnostics with zero additions; this is not a clean
strict-mypy claim. Exact published pins and the full Linux gate are still required.
