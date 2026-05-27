# Implementation Status

This top-level file is no longer the live implementation source of truth.

The previous version has been archived as a dated v1 snapshot at [2026-05-23-implementation-status-v1-snapshot.md](/C:/workbench/code/investment-optimiser/docs/archive/2026-05-23-implementation-status-v1-snapshot.md).

Use these documents instead:

- [system-design.md](/C:/workbench/code/investment-optimiser/docs/system-design.md) for the active product and architecture source of truth
- [2026-05-26-observed-vs-forward-inflation-inputs.md](/C:/workbench/code/investment-optimiser/docs/prds/2026-05-26-observed-vs-forward-inflation-inputs.md) for the bridge slice after the original v1 status snapshot
- [2026-05-27-v2-read-only-explanation-query-foundation.md](/C:/workbench/code/investment-optimiser/docs/prds/2026-05-27-v2-read-only-explanation-query-foundation.md) for the proposed next phase after the inflation slice

Why this was archived:

- the old file was a useful point-in-time audit, but it is stale relative to the current codebase
- later work introduced `policy_pack_v2`, DMO D10C observed-inflation refresh, an observed-inflation resolver, and additional explanation-layer groundwork
- keeping the old full document at top level risked it being treated as current implementation truth when it now functions better as historical context
