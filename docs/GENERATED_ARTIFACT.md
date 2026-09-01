# Generated Artifact v3

`openpine.generated_artifact.v3` seals:

- producer identity;
- consumer bundle and source hashes;
- PineVersionContext and catalog hash;
- LoweringPlan and Target Manifest hashes;
- emitted module and Source Map hashes;
- entrypoint;
- exact operations, capabilities and imports;
- one-to-one projection proof;
- explicit release-acceptance statuses.

A missing producer commit is represented as `UNCOMMITTED_LOCAL_BUILD`; no local Git probe
or fabricated SHA is used.
