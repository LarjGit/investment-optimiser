---
section: signal-layer
subsection: gry-computation
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

The GRY signal does not own a separate yield-calculation path. It reuses the same shared gilt yield engine used elsewhere in the system, so the signal layer and allocation engine cannot disagree on the yield of the same instrument.

### Shared computation path

For every conventional gilt in scope:

1. Take the market clean price from the common daily gilt price snapshot
2. Normalise price units to `per £100 nominal`
3. Apply `T+1` settlement
4. Apply DMO accrued-interest and ex-dividend rules
5. Solve GRY from dirty price using the shared `SciPy`-based root-finding implementation

The signal layer imports this service and uses its outputs only. It does not implement its own pricing, accrued-interest, settlement, or root-solving logic.

### Price source for held vs candidate gilts

The comparison must be made from the same market snapshot for both:

- gilts currently held
- gilts available in the candidate universe

Primary source for both is the daily LSE gilt market snapshot already used for the broader gilt universe. The imported portfolio CSV is not the authoritative comparison price for held gilts in this signal because it may be older than the candidate snapshot and would create false yield gaps. CSV price is fallback-only if a held gilt is missing from the market snapshot.

This means the signal answers:

> "Given today's market prices, is there a conventional gilt yielding materially more than the comparable conventional gilts I currently hold?"

not:

> "Does today's market beat whatever stale price happened to be in the latest portfolio import?"

### Universe and comparability rules

The headline GRY ranking is **conventional gilts only** by default.

Index-linked gilts are not mixed into the headline ranking unless the user explicitly provides an expected `RPI` assumption. Without that assumption:

- conventional gilts remain fully ranked and comparable
- owned index-linked gilts remain visible in holdings and risk views
- owned index-linked gilts are treated as `monitored but manual`
- index-linked gilts are excluded from the signal's yield-gap comparison and switch alert logic

If an expected `RPI` assumption is later supplied, index-linked gilts may be included by converting their real yield into a nominal-equivalent yield before comparison.

### Alert firing logic

The ranked conventional-gilt table is always available as an informational view.

The switch alert fires only when all of the following are true:

1. There is at least one currently held **comparable conventional gilt**
2. The best ranked conventional gilt in the market has a valid GRY
3. At least one held comparable conventional gilt has a valid GRY
4. The best market GRY exceeds the relevant held-gilt comparison by more than the configured threshold

If the portfolio contains no comparable conventional gilt holdings:

- still show the conventional-gilt ranking table
- suppress the switch alert
- show a plain-English note such as `No conventional gilt holdings to compare against`

This prevents a misleading "switch" alert when there is nothing in the current portfolio that can fairly be compared against the conventional-gilt league table.

### Failure handling

- If a market price is missing for a candidate gilt, exclude it from the ranking and surface a warning
- If a held gilt is missing from the market snapshot, fall back to the imported CSV price and mark the comparison as degraded
- If GRY solve fails for a gilt, exclude that instrument from alert comparison and show a named warning
- If no valid comparable held conventional gilts remain after exclusions, suppress the switch alert and keep the ranking informational only

The signal should fail soft, not disappear entirely.

## Decisions Made

- One shared GRY calculator across signaling and optimisation; no separate signal-layer maths
- One common daily market-price snapshot for held and candidate conventional gilts; CSV price is fallback-only
- Headline GRY ranking is conventional-gilt-only by default
- Owned index-linked gilts without an `RPI` assumption are monitored but manual, not yield-ranked
- Index-linked gilts may join the ranking later only after real-to-nominal conversion using a user-supplied `RPI` assumption
- Switch alert is suppressed when there is no comparable conventional gilt currently held
- Ranking table remains visible even when the alert is suppressed
- Missing prices or failed solves degrade gracefully with warnings rather than disabling the whole feature

## Remaining Open Questions

None
