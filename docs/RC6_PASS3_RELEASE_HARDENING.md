# Ast2Python 5.0.0rc6 — near-final pass 3

## Scope

This pass closes release engineering owned by Ast2Python:

1. exact local Git source identity;
2. clean detached-checkout rebuild;
3. source-manifest and evidence binding;
4. reproducible wheel and sdist;
5. clean wheel-only installation;
6. action pinning by full commit SHA;
7. local Python 3.13 test and coverage run;
8. honest syntax-only checks for Python 3.11 and 3.12;
9. a fail-closed exact RC5 differential boundary;
10. two independent audits of the final packet.

## Non-goals

The pass does not create GitHub branches, pull requests, tags, releases, deployments or
PineLib behavior. It also does not promote a local candidate to a coordinated stack
release when exact external evidence is absent.

## Gate model

`local_candidate_ready` requires all of the following:

- immutable source manifest;
- clean Git commit and tree;
- tests pass;
- coverage threshold passes;
- workflow action pins pass;
- wheel and sdist build passes;
- clean installation and `pip check` pass;
- detached-checkout reproduction passes.

`overall_release_ready` additionally requires:

- actual Python 3.11, 3.12 and 3.13 hosted jobs;
- hosted Ruff, Black and strict MyPy;
- an executable exact RC5 → RC6 differential with `REGRESSION=0`;
- exact PineLib 5.0.0rc6 target acceptance.

No gate authorizes merge, release or deployment. Authorization is a separate human
operation.
