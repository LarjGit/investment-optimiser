# PRD: V2 Read-Only Explanation And Query Foundation

Date: 2026-05-27

## Preface: Verified Current State

- Current code already includes an active default `policy_pack_v2`, split forward-inflation inputs, a `dmo_d10c` refresh path, `observed_inflation_cache`, an `observed_inflation_resolver`, replayable `allocation_runs`, and a small narrative explanation panel built from persisted run snapshots.
- The current inflation PRD already covers the observed-vs-forward inflation split, DMO D10C as the first observed source, fail-closed IL analytics, and deliberate separation from LLM, MCP, OpenBB, and broader v2 work.
- `docs/implementation-status.md` is useful as a secondary audit, but it is stale relative to the codebase. In particular, it still reflects a pre-`policy_pack_v2` snapshot and still describes a `D1D` XML path that newer source documents, solution notes, and current code supersede.
- This PRD assumes the inflation PRD is fully completed first, including the user-visible read-only observed-data surfaces and final cleanup of any bridge wording that still implies the split-assumption work is incomplete.
- Items that remain deferred after this PRD: actual local MCP server delivery, OpenBB integration, broad LLM explanation features, ONS CHAW ingestion, reintroducing excluded older 3-month-lag linkers, CVXPY migration, broader optimiser redesigns, and a separate analytics-validation hardening track if `rateslib` and DMO formula-vector tests are kept out of this slice.

## Problem Statement

Once the observed-vs-forward inflation work is complete, the product still lacks a stable internal read-only explanation and query layer over its persisted state. The app can already persist recommendations, scenarios, signals, and market caches, but the explanation surfaces are still mostly assembled directly in dashboard code and from ad hoc snapshot shapes.

That is good enough for a local dashboard, but it is not yet a strong v2 foundation. It makes later explanation work brittle, because future consumers would have to know too much about `app.py`, raw SQLite layouts, and evolving snapshot JSON details. It also weakens replayability and auditability because the persisted run contract does not yet capture the full resolved assumption state and provenance context that a durable explanation layer should read from directly.

If the project jumps straight from the inflation bridge slice into LLM or MCP work, the assistant layer would either wrap unstable dashboard logic or re-derive mutable state on demand. That would violate the design principle that explanation is read-only over authoritative persisted state and would make later assistant answers harder to trust, debug, and replay.

## Why This Phase Comes After The Inflation PRD

The inflation PRD is a bridge slice because it resolves one foundational ambiguity first: observed inflation data used for IL gilt pricing mechanics is not the same thing as forward inflation assumptions used for comparison and portfolio decisions.

That distinction should be finished before the broader v2 stream starts, because the next phase needs to build stable read contracts on top of the corrected model, not on top of the old scalar-RPI shortcut. Once the inflation split is complete, the most sensible next step is not broad LLM rollout or external market tooling. It is to make the deterministic persisted state explanation-ready, queryable, and reusable without allowing downstream layers to mutate or reinterpret policy truth.

This ordering preserves the intended separation:

- deterministic portfolio, market, signal, and allocation state stays authoritative
- explanation and research layers stay read-only over that state
- later MCP and LLM work becomes a thin adapter over stable internal contracts instead of a second system of record

## Source-Doc Basis For This Phase

- `docs/system-design.md` is the primary architectural source. It explicitly says the dashboard is an on-demand read layer over persisted data, the explanation layer is read-only over authoritative state, and local MCP read tools should expand only on top of that persisted-state model.
- `docs/external-tooling-research.md` is a primary research source. It recommends a local read-only MCP server over the app's own SQLite state plus OpenBB later for external context. That recommendation implies a stable internal read contract should come first. The same document also singles out `rateslib` validation as small trust-building hardening rather than a reason to front-load broad assistant work.
- `docs/prds/2026-05-26-observed-vs-forward-inflation-inputs.md` is a primary sequencing source. It explicitly keeps LLM, MCP, OpenBB, and broader v2 work out of the inflation slice and requires explanation and change-reporting to distinguish sourced observed inputs from user-authored forward assumptions.
- `docs/implementation-status.md` is secondary only. Where it conflicts with the three primary documents or the current codebase, this PRD resolves conflicts in favour of `docs/system-design.md`, `docs/external-tooling-research.md`, `docs/prds/2026-05-26-observed-vs-forward-inflation-inputs.md`, and verified code.
- The main reconciled conflict is that `implementation-status.md` still reflects an older DMO-reference story and an older v1-only status framing, while the verified codebase now includes `policy_pack_v2`, DMO D10C refresh, observed-inflation persistence, and a resolver path for IL analytics.

## Solution

Build a focused non-LLM v2 foundation that formalises how the app reads and explains authoritative persisted state.

From the user's perspective, this phase should make the optimiser able to answer, from stored records and current freshness metadata:

- what the latest authoritative recommendation is
- what changed since the previous run
- which assumptions and constraints were actually in force
- which trades were approved, friction-blocked, or risk-blocked
- which market and inflation inputs were authoritative, stale, fallback, or degraded

From the architecture's perspective, this phase creates stable internal read contracts and explanation-ready run snapshots first. Later MCP or LLM layers should consume those contracts as adapters, not invent their own query logic and not write back into deterministic state.

## User Stories

1. As a SIPP investor, I want the app to explain the latest recommendation from persisted records, so that I can trust it without re-running hidden logic.
2. As a SIPP investor, I want to compare the latest recommendation with the previous authoritative run, so that I can see what genuinely changed.
3. As a SIPP investor, I want recommendation explanations to show which assumptions were active at run time, so that I can understand the decision context instead of guessing from today's sidebar values.
4. As a SIPP investor, I want observed inflation provenance and my forward inflation assumptions shown separately in explanation views, so that the inflation split remains visible after the bridge slice is done.
5. As a SIPP investor, I want blocked trades grouped by friction and by risk, so that I can see whether an idea failed because of cost or policy.
6. As a SIPP investor, I want freshness and provenance summaries for the data behind a recommendation, so that I can judge whether a number was authoritative, stale, fallback, or degraded.
7. As a SIPP investor, I want scenario comparisons and coverage disclosure exposed through a stable read layer, so that portfolio downside explanations remain consistent across views.
8. As a SIPP investor, I want the explanation layer to stay whole-portfolio in scope, so that the product does not drift into being a gilt-only explainer.
9. As a SIPP investor, I want current-state explanation and historical-run explanation kept distinct, so that I can tell whether I am looking at today's state or a stored recommendation snapshot.
10. As a SIPP investor, I want decision-log context to remain connected to recommendations and signal history, so that later review is auditable.
11. As a maintainer, I want a stable internal read-only query contract over SQLite state, so that later MCP or LLM work can reuse one authoritative interface.
12. As a maintainer, I want replayable recommendation snapshots to store the actual resolved assumption values used for the run, so that explanations do not depend on mutable current UI state.
13. As a maintainer, I want explanation outputs to be traceable back to stored metrics and audit payloads, so that the app never emits unsupported narrative.
14. As a maintainer, I want backward-compatible readers for existing historical runs, so that introducing a richer read contract does not orphan prior data.
15. As a developer, I want deep read modules instead of dashboard-embedded SQL and JSON parsing, so that explanation logic can be tested in isolation.
16. As a developer, I want query models for recommendations, change reports, signal state, provenance, and inflation context, so that each consumer does not reinvent them.
17. As a future local assistant-layer maintainer, I want the eventual MCP server to wrap existing read services rather than raw tables, so that assistant tooling stays thin and honest.
18. As a product maintainer, I want the docs and status narrative reconciled with the live contracts, so that future planning does not restart from stale assumptions.
19. As a portfolio user, I want the app to preserve the separation between deterministic portfolio state and later assistant layers, so that no assistant can silently create recommendation truth.
20. As a portfolio user, I want the system to preserve auditability, explainability, and replayability even as explanation surfaces become richer, so that confidence grows instead of eroding.

## In Scope

- A formal internal read-only query layer over persisted SQLite state for recommendation, scenario, signal, freshness, provenance, and decision-log views.
- A richer versioned recommendation-snapshot contract that persists the actual resolved run-time assumption state needed for replayable explanation.
- Read-only explanation and change-reporting services that consume persisted state and replace ad hoc dashboard-specific data assembly where practical.
- Provenance and freshness read models for recommendation-relevant sources, including observed-inflation state already introduced by the inflation slice.
- Dashboard adoption of the new read services for explanation, change reporting, and provenance display where that improves contract clarity.
- Backward-compatible readers for existing historical records and minimal schema-version evolution where needed.
- Documentation and status reconciliation required to make the new contracts the clear source of truth for later work.

## Implementation Decisions

- This phase should create an internal read-only service layer first, not an assistant integration. The service layer is the product-facing v2 foundation; actual MCP or LLM tooling sits on top later.
- The read layer should expose a small set of stable query contracts such as: latest portfolio state summary, latest authoritative recommendation bundle, run-to-run change bundle, signal state bundle, market-data freshness and provenance bundle, and observed-vs-forward inflation context bundle.
- Explanation remains read-only over authoritative persisted state. This phase should not introduce a free-form narrative table or any assistant-authored write path.
- The main persistence change should be to enrich the existing replayable recommendation snapshot rather than invent a parallel explanation store. Historical runs must remain readable, but newer runs should carry more explanation-ready context.
- The recommendation snapshot contract should store concrete run-time assumption values, not only policy version labels and lists of constraint names. At minimum it should be able to reconstruct the actual thresholds, inflation assumptions, scenario magnitude, benchmark choice, friction assumptions, and other active knobs that materially shaped the run.
- The recommendation snapshot contract should also persist enough recommendation-context metadata to support later explanation without rereading mutable dashboard state. That includes structured trade outcomes, scenario results, binding-constraint details, and a compact provenance or freshness summary for recommendation-relevant upstream inputs.
- The phase should preserve the design choice that no dedicated explanation table is required. Explanation outputs should still be reconstructed on demand from persisted state, but from cleaner and more stable contracts than today.
- The internal read contracts should distinguish clearly between two views: current authoritative state from live tables and historical authoritative state from a stored recommendation run. A consumer must not have to infer which one it received.
- The dashboard should consume the new read services instead of assembling explanation state directly from raw SQL rows and ad hoc JSON shape knowledge inside one large presentation file.
- The implementation should use deep modules with narrow typed interfaces for read models, comparison logic, and provenance reporting. The goal is to make later MCP wrapping straightforward without binding that work into this phase.
- The actual local MCP server should remain later work. This PRD should make the codebase MCP-ready, not MCP-complete.
- `rateslib` validation and DMO formula-vector tests should remain separate hardening work rather than the core of this PRD. They improve trust in analytics, but they do not define the explanation/query foundation itself.
- ONS CHAW should remain a follow-on data-hardening path, not a prerequisite for this phase. The read layer should be designed so a future second observed-inflation source can slot into provenance and validation contracts later.
- Documentation reconciliation should be part of delivery, not a postscript. The finished phase should update the repo's own narrative so later planning starts from the corrected contracts.

## Testing Decisions

- Good tests in this phase should validate externally consumed read contracts, replay behaviour, and provenance semantics rather than internal SQL text or presentation implementation details.
- Query-layer tests should seed representative SQLite state and assert the returned structured bundles for recommendations, changes, signals, freshness, provenance, and inflation context.
- Recommendation-snapshot tests should verify schema evolution and backward compatibility. Existing historical runs must still load, while newer runs must expose the richer assumption and provenance contract.
- Explanation-service tests should verify that run comparisons distinguish at least: changed assumptions, changed source freshness or provenance, changed trades, changed scenario outputs, and changed binding constraints.
- Read-only guarantees should be tested explicitly. The explanation and query services must not mutate authoritative tables as a side effect of rendering or querying.
- Dashboard-level tests should stay lightweight and focus on contract consumption: the page should read from the new services and present the expected summaries, not recompute recommendation truth.
- Prior art should come from the existing repository patterns around `allocation_runs`, `recommendation_change_summary`, `narrative_explanation`, `refresh`, `policy_pack`, `dmo_d10c`, `gilt_analytics`, and app smoke tests.
- If a schema version increment or nested snapshot-contract revision is introduced, add regression tests proving older stored runs remain explainable and newer runs expose the richer fields.

## Out of Scope

- Broad LLM explanation features, model orchestration, prompt work, or assistant-authored narratives
- Delivery of a local MCP server or any external MCP integration
- OpenBB integration or other external market-context tooling
- ONS CHAW ingestion, fallback logic, or dual-source observed-inflation validation
- Reintroducing excluded older 3-month-lag index-linked Treasury Stock linkers
- `rateslib` cross-check integration or DMO formula-vector fixtures if those are kept as a separate hardening track
- CVXPY migration, weighted multi-scenario objectives, confidence tightening, explicit cash-flow solver inputs, or other broader optimiser redesigns
- Minor layout polish or dashboard-only visual tweaks unrelated to the new read contracts

## Sequencing Assumptions

1. The observed-vs-forward inflation PRD lands first and leaves the product with a stable split-inflation contract.
2. Any small analytics-validation hardening that the team wants immediately can land just before this phase or in parallel, but it should stay separate from the main explanation/query foundation.
3. This PRD then establishes the internal read-only explanation and query contracts over persisted state.
4. Only after those contracts are stable should the repo add a local read-only MCP server as an adapter.
5. Only after the local read contract and optional MCP adapter are stable should broader LLM explanation work and external market-context tooling expand on top.

## Dependencies On The Inflation PRD Being Complete

- The split forward-inflation policy contract must be stable and versioned.
- The observed-inflation refresh and resolver path must be complete enough that explanation services can treat it as authoritative persisted state rather than an in-flight bridge.
- The app must no longer rely on a legacy scalar inflation assumption for analytics.
- Read-only observed-data presentation for the inflation inputs should be finished, because this phase depends on explanation surfaces consuming that contract rather than inventing a new inflation UI.
- The completed inflation slice should leave a clear provenance story for observed inflation so the new query layer can report it cleanly.

## How This Phase Relates To Later LLM And External-Tooling Work

This PRD is the foundation for later assistant work, not the assistant work itself.

Later LLM features should answer questions by reading the contracts created here. They should not read arbitrary dashboard internals, rerun recommendation logic silently, or create authoritative state. Likewise, a later local MCP server should be a thin read-only adapter over the services defined in this phase, and OpenBB or any other external market-context tooling should remain a separate context source rather than becoming a second recommendation engine.

In short:

- this phase stabilises internal truth and explanation access
- a later MCP phase exposes that truth safely
- a later LLM phase narrates and questions that truth
- external tooling later adds market context, not product authority

## Further Notes

- The current codebase already points in this direction: persisted `allocation_runs`, change-summary helpers, signal history, observed-inflation caching, and narrative panels exist. What is missing is a formal reusable read contract that makes those pieces reliable inputs for v2.
- The biggest reason to do this before MCP or LLM work is not convenience. It is product integrity. The repo's core values of auditability, replayability, and explainability are easiest to preserve when the assistant-facing layer stays downstream of stable deterministic contracts.
- Because `docs/implementation-status.md` is stale relative to the code, part of the acceptance bar for this PRD should be leaving the repository with one coherent story about active policy version, DMO source contracts, and the role of the explanation layer.

## Appendix: Already Covered By The Inflation PRD

- Separating observed inflation data from forward inflation assumptions
- Using DMO D10C as the first observed-inflation source
- Replacing the single forward RPI field with pre-2030 and post-2030 policy inputs
- Keeping ONS CHAW visible but deferred
- Keeping LLM, MCP, OpenBB, and broader v2 work out of the bridge slice
- Preserving the principle that explanation must be able to say what came from sourced observed data versus user-authored forward assumptions

## Appendix: What Remains Deferred After This PRD

- Local read-only MCP delivery
- Broad LLM explanation and question-answering features
- OpenBB or comparable external market-context tooling
- ONS CHAW ingestion and dual-source inflation validation or fallback
- Reintroduction of currently excluded older 3-month-lag linkers
- Separate analytics-validation hardening with `rateslib` and DMO formula vectors if not scheduled independently
- Broader optimiser and solver evolution beyond what is needed to support the read-only explanation/query foundation
