# Stage 2 nominal compiler block

Baseline: `1d79941c992c0523f1a4c7d632066a884ba18898`, exactly the RC6 lifecycle pin.
The pinned tree is one functional commit ahead of `origin/release/5.0.0rc6`;
candidate `e32dc46` only adds CI preservation for that commit. No old tree was
copied over the pinned implementation.

The compiler now lowers UDT constructors/defaults, reads, writes, shallow copies,
typed reference bindings/history, enum values/bindings/history, and receiver-typed
methods. Nominal identity contains the source checksum and declaration node ID;
method dispatch uses the producer's exact declaration symbol, not a method name.
The compiler requires the exact `compiled_nominal_types` runtime contract before
emitting calls. Heap schema validation, enum coercion, checkpoint encoding and
field rollback remain owned by PineLib. No generated Python class duplicates
the runtime object model.

## Independent expectations and real failed investigations

Tests in `tests/test_nominal_language_execution.py` use hand-derived expectations.
They do not claim external TradingView export verification.

1. Initial UDT compilation failed the producer's `qualifier_enforced` release
   axis, enum member emission had no target binding, and methods did not have a
   compiler receiver binding. These were executable gaps, not diagnostic wording.
2. The first nominal run had 35 passing cases and one failing v5 enum comparison:
   missing enum history compared to a member returned `false` instead of `na`.
   PineLib corrected nominal NA comparison with separate versioned tests.
3. A new draft fill-recalculation hypothesis expected `[1, 1]` after the second
   deferred callback for `varip n` and ordinary `var ordinary`, both incremented
   by `once`. The real callback returned `[2, 1]`. The original draft also used a
   synthetic phase without deferred bar commit, which did not exercise rollback;
   the committed test uses `ORDER_FILL_RECALC`, `defer_bar_commit=True`, and the
   actual `finalize_bar()` boundary.

The third failure was an incorrect new test assumption. The independently read
[conditional structures documentation](https://www.tradingview.com/pine-script-docs/language/conditional-structures/)
defines `once` as equivalent to an ordinary persistent boolean flag and describes
completion rollback before final commit. The
[execution model documentation](https://www.tradingview.com/pine-script-docs/language/execution-model/)
explicitly allows rollback on historical bars with order-fill recalculation.
Together these rules imply the completion and ordinary counter roll back, while
the `varip` counter retains both increments. Therefore `[2, 1]` is the independent
specification-derived expectation. After final bar commit, both the uninterrupted
and checkpoint-restored executions remain `[2, 1]`. The implementation of `once`
was not changed to make the flag intrabar-persistent.

Record this draft test-assumption correction independently from functional
changes when assembling commits. It does not delete or weaken an existing test.

This block does not by itself accept Stage 2. Full versioned catalog/oracle,
coordinated CI, protected-worker and package acceptance remain separate gates.
Performance was not measured in this block.

## Local validation

- New nominal execution/library matrix: 48 passing tests on Python 3.11 and
  Python 3.13. Cases include exact locked imports, same-named types in different
  owners' same-named libraries, transitive dependency invalidation, enum state,
  method callsite state, and JSON checkpoint continuation.
- Existing scalar/reference/import/intrabar/direct-emitter regression selection:
  283 passing tests on Python 3.11.
- First full Python 3.11 run: 669 passed, three Windows infrastructure failures
  (before the final twelve additional nominal cases were added).
- Full Python 3.13 run: 681 passed, three Windows infrastructure failures, 125.52s.
  Final collected inventory is 684 cases, including 48 added cases.
- The infrastructure failures are two release-candidate tests whose nested Git
  process raises `WinError 5`, and the admission symlink test whose setup raises
  `WinError 1314`. These tests were neither skipped nor weakened.
- Ruff on every changed compiler/test module and `git diff --check` passed.
- A real Python 3.11 wheel build with `--no-isolation` failed because the shared
  test environment lacks `setuptools.build_meta`. This is not a successful
  package-build receipt; the coordinated environment must install the declared
  build dependencies and rerun it.
