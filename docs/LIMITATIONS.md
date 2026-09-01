# Limitations and honest acceptance boundary

The Stage 4 compiler-owned scope is not a claim of TradingView runtime parity.

Current external blockers:

1. no exact PineLib `5.0.0rc6` Target Manifest/wheel was available in the working set;
2. the corrected Pine2AST RC6 ZZ-2 bundle contains call arguments whose
   `parameter_index`/binding facts are incomplete, so strict Ast2Python admission rejects
   it instead of re-binding locally;
3. exact RC5 compiler artifacts were unavailable for a byte-level old/new differential;
4. Python 3.11/3.12 and Ruff/Black/MyPy require hosted/external gates in this environment.

The six corrected version vectors and 22-case normative lowering corpus are accepted.
Merge and release remain unauthorized until all external blockers are closed.
