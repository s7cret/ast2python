# Binding locked Pine library sources to generated artifacts

The public production compilation entrypoint accepts `linked_source=LinkedSource`.
It verifies the reconstructed source projection and checks the consumer bundle's
source hash before lowering. An unresolved `library.import` cannot silently vanish
from a successful artifact, even if the imported alias is not used.

```python
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.libraries import link_libraries
from ast2python import compile_consumer_bundle
from ast2python.lowering import load_pinelib_target_manifest

linked = link_libraries(root_pine, admitted_store, source_name="main.pine")
bundle = build_consumer_bundle(linked.code, producer_commit=pine2ast_sha)
compiled = compile_consumer_bundle(
    bundle,
    linked_source=linked,
    target=load_pinelib_target_manifest(),
    producer_commit=ast2python_sha,
    expected_pine2ast_commit=pine2ast_sha,
)
```

The previously reserved `external_library_dependency_hashes` artifact field now
contains the exact reachable publication refs and an `@linkage` receipt hash.
These identities contribute to the existing build manifest identity. Changing a
transitive source invalidates the build/artifact identity; changing only the outer
artifact hash does not hide that mutation. Legacy artifacts with an empty map keep
their established formula and verification behavior. The existing Contracts schema
already allows the map; no alternative broker schema is introduced.

The root artifact's source hash is the linked virtual source, not the original
unlinked consumer. The latter remains in the linkage receipt. Preserve the receipt
for original-file diagnostics. The runtime runs the same generated UDFs, state
slots, series and checkpoint mechanism; no library files, imports or arbitrary
resolvers need to be exposed inside the worker.

This binds explicit dependencies; it is not a completed cache hit/miss service,
remote library registry, proof of publisher identity or support for every exported
Pine type. Same-language scalar import constraints are owned by Pine2AST's linker.
