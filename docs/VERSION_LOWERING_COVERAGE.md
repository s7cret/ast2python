# Version lowering coverage

The Stage 4 corpus contains admitted, hash-pinned cases for every Pine version v1–v6.
The version differential gate contains 25 rule pairs across adjacent versions.

Coverage claims are scoped:

- **compiler core line/branch coverage:** measured by the delivered coverage report;
- **normative corpus:** exact expected IR/module/source-map/artifact hashes for listed cases;
- **version rules:** eager/lazy logic, division, conditional and loop-bound recipes;
- **official Pine symbol surface:** not claimed by Ast2Python;
- **PineLib runtime and TradingView oracle:** not claimed.
