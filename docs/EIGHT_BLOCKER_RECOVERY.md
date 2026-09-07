# Eight-blocker recovery contract

Target blockers from the certified Top-30: BAC, BBVA, CIBR, SCHW, TRV, VEA, XLE, XLF.

The recovery does not hardcode prices, ratios, targets, or PASS decisions by ticker.

## Rules

- Missing or market-inconsistent local quotes may receive an analytical-only local reference derived from underlying price × robust market CCL / validated ratio.
- This analytical recovery never creates bid/ask liquidity or execution readiness.
- A canonical universe ratio missing from the current Comafi scrape may receive `RATIO_VALIDATED_CANONICAL_CCL` only when an observed local quote independently reconciles its implied CCL to the robust market CCL within 5%; the local gate remains `PASS_WITH_WARNING`.
- Official Comafi ratios remain the preferred ratio source.
- ETF direct constituent lookups remain globally capped at 60; the per-ETF Top-N cap is 25 so a fund estimated to need 21 lookups is not blocked by an arbitrary 20-call ceiling.
- G4 applies its existing local warning penalty to `PASS_WITH_WARNING`; execution remains a separate downstream gate.

## Acceptance

`Top-N=30 -> Valuation Ready=30 -> G4 evaluated=30 -> BLOCKED_BY_DATA=0`.

Any failure remains explicit and auditable rather than being converted to a synthetic PASS.
