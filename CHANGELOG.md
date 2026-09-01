# Changelog

## 5.0.0rc6 — Stage 4

- Made `pine2ast.consumer_bundle.v1` the only production input.
- Removed raw-AST translation, tolerant wrappers, the local binder/signature registry,
  local type inference, compatibility flags, request/visual/library stubs and runtime
  contract aliases.
- Added immutable compilation sessions and typed `ast2python.lowering_plan.v1` IR.
- Added version-exact recipes for Pine v1–v6 and exact Target Manifest admission.
- Added deterministic self-contained Python emission, Source Map v2 and
  `openpine.generated_artifact.v3`.
- Added a 22-case normative corpus, 25 adjacent-version differential cases,
  44 bundle mutants, 40 IR mutants, 30 artifact mutants and a deterministic 10,000-case
  fuzz gate.
- Added property, performance, security, coverage, package-integrity, reproducibility,
  SBOM and provenance gates.
- Preserved the release stop boundary: exact PineLib RC6 acceptance and external
  Python/tooling matrix remain mandatory before merge or release.

## 5.0.0rc6 — near-final pass 3

- Added a fail-closed release-candidate hardening model with separate local and external gates.
- Added source-manifest verification and exact local Git commit/tree evidence.
- Added Python 3.11/3.12/3.13 syntax-compatibility checks without misrepresenting them as runtime CI.
- Added a GitHub Actions workflow with every third-party action pinned to a full commit SHA.
- Added an exact-RC5 differential runner that refuses to infer a pass when the reviewed RC5 wheel or classified corpus results are absent.
- Added deterministic review-packet and independent-audit tooling.
- Preserved the stop boundary: local candidate readiness never authorizes merge, release, or deployment.
