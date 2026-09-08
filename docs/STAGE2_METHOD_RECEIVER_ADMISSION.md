# Ordinary method receiver admission (A2)

This change consumes the producer's explicit ordinary-method receiver proof. It
is based on compiler `95a14be4be8987faafb3e7629c744e698fd9f134`; it does not add a
second receiver evaluator or runtime ABI.

`BundleAdmissionService` negotiates the producer's `ast_replay_limits` keyword only
for AST2.1. Genuine AST2.0 bundles call the old public verification signature.
There is no `TypeError` retry that could bypass a new verifier. New feature bundles
require the exact `method_receiver_qualifiers_v1` capability, producer closed replay
API and corresponding AST field/revision. A previous consumer rejects the feature.
Configured compiler limits are clamped to the producer's closed maximum profile.

`StrictASTView` preserves the admitted field and exact revision. Only after full
producer verification and consumer invariants does the existing lowering builder
remove this one consumer-only proof capability from required execution capabilities.
All preexisting runtime, nominal registry, varip reference and library context
capabilities retain their former treatment. The generated artifact schema, runtime
manifest and runtime session API do not change.

The producer owns source-free canonical reconstruction, exact catalog policy and
fresh comparison of all semantic facts/calls. Library 1.1 retains verified context
reconstruction and real source reparse. The compiler continues consuming ordinary
method call facts, so receiver evaluation is neither duplicated nor reordered.

New independent literal execution tables cover simple/input/series receivers,
named/default parameters, tuples, same-spelling user `nz` methods and receiver
side effects. Lifecycle controls compare ordinary method local `var` state across
rollback, abort/retry and JSON checkpoint continuation. Linked-source and nominal
registry/varip array controls use the existing verified artifact and runtime-owner
factory path. Expected values are manual constants, not recorded SUT output.

Historical 89f07 producer / 95a compiler API matrices demonstrate that all old
AST2.0 pairs remain admitted and only the new/new pair admits AST2.1. They are
retained as historical pair evidence, not relabelled as the final 05d7 producer
composition. Exact execution counts, source hashes and Windows packaging failures
belong to the final receipt. Exported-library method linkage and the v5 reference
annotation exception remain outside this bounded implementation claim.
