# Explicit method receiver emission

Admit `user_method_function_calls_v1` only through the coordinated producer's exact
consumer contract and bounded semantic replay. Remove this compiler-only feature
from runtime capability requirements; the generated module still uses the existing
`invoke_function_v1` operation, callsite paths, series, heap and transactions.

For function-style methods, the receiver is the checked, named argument at parameter
index zero. Its nominal type is normalized through the existing runtime type owner,
just like a dot receiver; the textual linker name is not compared directly with a
runtime nominal identity. No synthesized wrapper changes written-callsite state.

All exact user calls now evaluate explicitly supplied arguments in their written
source order when building the runtime argument dictionary. A dot receiver remains
first; a named explicit receiver may be written later. Binding still uses declaration
parameter identities. Omitted defaults are evaluated after supplied arguments. This
fixes the old declaration-order evaluation of named arguments without inventing
another evaluator or evaluating receiver expressions twice. Default ordering versus
arbitrary side effects is not independently certified for all Pine constructs.

Tests cover both Pine versions, scalar/collection/UDT/enum receivers, chaining,
transitive private helpers, exact namespace selection, mixed callsites, loop reuse,
UDT ordinary/varip fields, realtime rollback and JSON restore. Expected numerical
values are manually derived from the source bodies, not recorded TradingView runs.
No whole-backtest performance or full language conformance is claimed.
