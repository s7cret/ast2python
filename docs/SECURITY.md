# Security and safety model

AST2Python is a code generator. It should be treated as a trusted build-time component, not as a sandbox for arbitrary untrusted AST payloads.

Safety principles:

- validate AST envelopes before lowering;
- fail closed for unsupported realtime, request and external-library behavior;
- keep generated modules targeting explicit PineLib runtime APIs;
- avoid silent parity fallbacks in production profile;
- expose diagnostics and source maps for auditability.
