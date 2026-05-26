# PRD: Observed Vs Forward Inflation Inputs

Date: 2026-05-26

## Problem Statement

The investment optimiser is a whole-portfolio SIPP decision tool, but its current
index-linked gilt handling still collapses two different concepts into one RPI
input:

- observed inflation data needed to interpret current index-linked gilt pricing
- forward inflation assumptions needed to compare future real returns against
  nominal alternatives

That ambiguity creates product and engineering problems. It makes the dashboard
look as if the user is manually supplying both current pricing mechanics and a
future market view. It makes the policy pack look less authoritative than the
updated system design intends. It also makes explanation, replay, and audit
weaker because the app cannot cleanly say which parts of an index-linked gilt
view came from refreshed public data and which parts came from the user's own
forward assumptions.

The near-term need is to make this distinction explicit without changing the
product into a gilt-only tool and without dragging broader v2 ideas into the
same implementation slice.

## Solution

Introduce a clear two-part inflation model for the in-scope index-linked gilt
flow:

- observed inflation inputs are refreshed from authoritative public sources and
  used for pricing mechanics and current-state interpretation
- forward inflation assumptions remain user-authored policy inputs and are used
  for real-to-nominal comparison and portfolio decision-making

For the near-term slice, the app should also replace the single forward RPI
assumption with two explicit forward assumptions:

- a pre-2030 forward inflation assumption
- a post-2030 forward inflation assumption

This keeps the optimiser aligned with the current system design, makes the IL
gilt path more explainable, and preserves the full-product framing: the whole
portfolio allocator remains the product, while the inflation redesign improves
one important decision subsystem inside it.

## User Stories

1. As a SIPP investor, I want the app to distinguish between current observed inflation data and my own forward inflation view, so that the recommendation logic is intellectually honest.
2. As a SIPP investor, I want observed inflation inputs to refresh automatically from public sources, so that I do not have to type market mechanics into the sidebar by hand.
3. As a SIPP investor, I want to set a forward inflation assumption up to January 2030, so that I can express my view before the RPI methodology change.
4. As a SIPP investor, I want to set a separate forward inflation assumption after January 2030, so that long-dated index-linked gilts are assessed against a more realistic regime.
5. As a SIPP investor, I want the app to show when an index-linked gilt is using observed data plus forward assumptions, so that I can understand how its yield comparison was built.
6. As a SIPP investor, I want the app to explain when an index-linked gilt is excluded from ranking or recommendation logic, so that I know whether the omission is deliberate or due to missing data.
7. As a SIPP investor, I want stale or missing observed inflation data to surface as a visible warning, so that I do not mistake degraded analytics for trusted outputs.
8. As a SIPP investor, I want the recommendation and signal layers to use the same inflation assumptions, so that different parts of the app do not contradict each other.
9. As a SIPP investor, I want the dashboard to make clear that observed inflation data is not the same as my market view, so that I can change one without silently changing the other.
10. As a SIPP investor, I want long-dated index-linked gilts to reflect the post-2030 regime explicitly, so that the comparison against conventional gilts is not overstated.
11. As a SIPP investor, I want current out-of-scope old 3-month-lag Treasury Stock linkers to remain excluded unless the product deliberately reintroduces them, so that scope does not quietly expand mid-slice.
12. As a SIPP investor, I want my chosen forward inflation assumptions to persist consistently across tabs and reruns, so that the whole app reflects one active policy state.
13. As a SIPP investor, I want refreshed inflation data to carry source and freshness information, so that I can judge whether a number is authoritative, fallback, or stale.
14. As a SIPP investor, I want recommendation explanations to tell me whether a change came from refreshed observed data, changed forward assumptions, or both, so that I can understand what really moved.
15. As a SIPP investor, I want index-linked gilt analytics to fail closed when required inputs are missing, so that the app never invents precision it does not have.
16. As a portfolio user, I want the rest of the non-IL portfolio flow to behave as before, so that this redesign improves one subsystem without destabilising the whole optimiser.
17. As a developer, I want a stable observed-inflation data contract, so that pricing logic, signals, scenarios, and explanations can all rely on the same resolved inputs.
18. As a developer, I want the inflation logic extracted into deep, testable modules, so that policy changes do not require fragile edits across the whole app.
19. As a maintainer, I want the policy pack to express the forward inflation schema explicitly, so that future policy revisions are machine-readable and versioned.
20. As a maintainer, I want refreshed inflation datasets to be persisted with provenance and as-of semantics, so that historical runs remain replayable and debuggable.
21. As a maintainer, I want run history and explanations to record the exact forward assumptions in force, so that later review can reconstruct why a recommendation was produced.
22. As a maintainer, I want the near-term implementation to stay separate from LLM and MCP work, so that the delivery slice remains small enough to ship cleanly.

## Implementation Decisions

- This PRD covers a near-term subsystem redesign inside the whole-portfolio optimiser. It does not redefine the product as a gilt-only tool.
- The redesign introduces an explicit observed-inflation data flow and an explicit forward-inflation policy flow. They are separate concepts, separate inputs, and separate explanation surfaces.
- The forward assumption schema moves from one scalar field to two named fields: one for pre-2030 and one for post-2030. The policy pack becomes the canonical machine-readable source of those keys and defaults.
- The implementation should create a new policy-pack revision rather than silently mutating the frozen v1 artifact. Historical policy versions remain replayable.
- Observed inflation inputs should enter the system through the refresh coordinator as dedicated source data, not through manual dashboard entry and not through ad hoc analytics-time fetching.
- The near-term minimum source requirement is a direct observed-inflation feed that supports current IL pricing mechanics cleanly. The design should allow both DMO D10C and ONS CHAW later, but the initial delivery may choose a single primary source if that keeps scope tighter.
- The near-term implementation should use DMO D10C as the initial observed-inflation source because it is the most direct fit for current IL pricing-state mechanics and keeps the delivery slice smaller.
- ONS CHAW remains a deliberate follow-up option for observed RPI sourcing, validation, and fallback. It is deferred from this implementation slice, not dropped from the design, and should stay visible in the backlog as follow-up work.
- A dedicated observed-inflation resolver should be introduced as a deep module. Its job is to take refreshed observed data plus settlement context and return the pricing-state inputs required by IL analytics. Other modules should consume that interface rather than reimplementing inflation mechanics independently.
- The IL analytics module should consume two resolved inputs: observed pricing-state data from the resolver and forward assumptions from the active policy state. It should not infer one from the other.
- In-scope index-linked gilts should only enter ranking, switch logic, and candidate-universe decisions when the required observed input and forward assumptions are both available. Missing inputs must produce explicit warnings rather than silent fallback to the old single-assumption behaviour.
- Currently excluded old 3-month-lag Treasury Stock linkers remain out of scope for this PRD. The design should not require their reintroduction in order to ship the near-term slice.
- Persistence should add explicit storage for observed inflation data and carry provenance fields sufficient to answer provider, fetched-at timestamp, as-of date, confidence tier, and degraded-or-cached status.
- This slice should also persist enough contextual metadata for later explanation to say whether an IL view came from authoritative observed data, fallback behaviour, or user-authored forward assumptions.
- The refresh coordinator should schedule observed-inflation refresh before IL analytics and before any downstream signal or recommendation steps that depend on resolved IL data.
- Dashboard controls should be updated so the user edits only forward assumptions. Observed inflation data should render as read-only sourced context with freshness and provenance signals.
- The current single-file dashboard structure should not be expanded further for this slice. Sidebar assumption handling and IL-specific explanation rendering should be extracted into focused presentation helpers or modules.
- Explanation and change-reporting surfaces should distinguish between three drivers of change: refreshed observed inflation data, changed forward assumptions, and non-inflation market changes.
- The recommendation, signal, and scenario layers should share one common resolved-inflation contract so they do not drift in treatment of the same instrument.
- The delivery should preserve existing behaviour for conventional gilts and non-gilt assets unless a change is a direct consequence of the new shared assumption schema or shared provenance model.

## Testing Decisions

- Good tests in this slice should verify externally visible behaviour and durable contracts, not internal implementation details. A test should prove that a given combination of refreshed observed data, forward assumptions, and portfolio context produces the expected eligibility, warnings, persistence, and recommendation-facing outputs.
- The observed-inflation resolver should receive focused unit tests because it is the deepest new module and the main place where pricing-state mechanics can become subtle.
- The policy-pack assumption schema should receive regression tests so that pre-2030 and post-2030 defaults, labels, and typing remain stable.
- The refresh path should receive tests covering successful observed-inflation refresh, source failure, stale-data handling, and correct ordering relative to downstream analytics.
- The IL analytics flow should receive tests covering eligibility when both input classes are present, exclusion when observed data is missing, and explicit warnings when forward assumptions are absent.
- The signal and ranking behaviour should receive tests proving that index-linked gilts only join comparison when the full required input set exists and that old excluded linkers remain out of scope.
- The persistence layer should receive migration and round-trip tests for any new observed-inflation tables and provenance fields.
- The dashboard layer should receive behaviour tests for the new sidebar assumptions, the read-only observed-data display, and the visible explanations for stale, missing, or fallback inflation inputs.
- The explanation and audit surfaces should receive tests proving that change attribution can distinguish observed-data changes from forward-assumption changes.
- Existing parser, analytics, signal, refresh, and scenario test patterns in the codebase should be used as prior art. The new tests should follow those styles rather than introducing a separate testing idiom for this slice.

## Out of Scope

- Reintroducing excluded old 3-month-lag Treasury Stock linkers into the active candidate universe
- CVXPY migration or any other solver-family change
- LLM explanation layers, local MCP tools, or external assistant integrations
- OpenBB integration or other v2 market-context tooling
- Broad optimiser changes unrelated to inflation-input separation
- A full same-day provenance retrofit across every historical table in the database
- Any redesign that turns the product into a fixed-income-only or gilt-only tool
- Monte Carlo or probabilistic scenario modelling

## Further Notes

- This PRD is intentionally narrow. It captures a near-term design commitment that now affects policy, refresh, analytics, persistence, explanation, and UX at the same time.
- The main delivery test is conceptual as much as technical: after this slice, the app must be able to explain which parts of an IL-gilt view came from refreshed public data and which parts came from the investor's own forward assumptions.
- The most important discipline in implementation is to avoid backsliding into a single hidden "RPI assumption" concept under a new name.
