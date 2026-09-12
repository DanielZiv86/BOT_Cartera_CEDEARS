# BOT Cartera CEDEARS — Project State

_Last updated: 2026-09-11 (end of session)_

## Objective

**Single mandate (redefined 2026-09-12, supersedes any earlier "capital preservation is primary" framing): build a CEDEAR portfolio, using the capital available, that reaches or exceeds $20,000 additional USD by 2028-09-11** (24 months from 2026-09-11), on top of current NAV (~$49,087). Risk management is not a competing constraint against this goal -- it exists in service of reaching it reliably. G4/Bear-case discipline, correlation-awareness and fail-closed data handling all still apply; what changed is that sizing is no longer capped by an independent "preserve capital first" ceiling, and every new-buy proposal must be evaluated against the whole current portfolio (existing holdings' own risk + correlation), not in isolation. Weekly pace is expected to fluctuate with what the market actually offers -- the system does not fabricate or relax fundamental analysis to hit a return number on schedule; see `goal_tracking` for the running pace metric.

The pipeline must not manufacture deployment candidates. `NO_NEW_DEPLOYMENT` remains valid unless downstream stages, using consistent lineage and verified data, justify otherwise.

## Current production architecture (post Fase 2, 2026-09-11)

```
Comafi universe -> BYMA/Caja negotiability validation -> real eligible universe (~235-304 instruments, count is dynamic)
  -> Valuation (FULL universe, broad-universe Finnhub consensus scenario)
  -> Research value-first ranking (equities ranked by value_score/fundamentals;
     technical screening_score is a binary entry-timing gate only; ETFs keep a
     separate technical-only ranked track) -> immutable Top-30
  -> Deep Scenario Review V2.2 (sector-aware: CORPORATE/FINANCIALS/ENERGY archetypes)
  -> G4 Cash Hurdle -> Risk -> Committee (allocator ranks G4_PASS by risk_adjusted_er,
     risk-budget fill; goal_tracking reports pace vs the $ objective)
```

**This is a change from the architecture description in the previous version of this file** (which had Research/technical-screening picking the Top-30 *before* Valuation ran on just those 30). That old order was found, and fixed, this session — see "Fase 2" below.

Key rules (unchanged):
- Valuation now runs on 100% of the canonical eligible universe (used to be Top-30 only).
- Deep Scenario Review / G4 remain limited to the immutable Top-30, selected by the value-first ranking.
- G4 requires Bull/Base/Bear scenarios, probabilities, net expected return, downside, costs, uncertainty penalty and explicit comparison versus cash.
- No artificial deletion/replacement of Top-30 names to force G4 success.
- Lineage must remain pinned across stages.
- Universe counts must be dynamic, never hardcoded to historical fixed values (316/305/304 — the exact count moves as the canonical universe is refreshed; treat any hardcoded count as a bug).
- IWDA remains an explicit mandate exception and must remain inside the universe with normal screening/scoring and traceability.

## Session 2026-09-11 summary (this session)

Started from a working but economically stuck pipeline: G4 had **never produced a single PASS candidate** despite passing all its own unit tests. Root-caused and fixed a chain of real economic/methodology bugs, each validated against real market data via GitHub Actions before merging, in this order:

1. **Goals-based hurdle tracking** (PR #12) — `src/portfolio/goals.py`, `src/orchestration/build_investment_committee.py`: tracks required annual return toward the $20k/24mo objective; informational, never gates.
2. **ENERGY archetype missing bull-ordering floor** (PR #13) — `deep_scenario_engine.py::_energy_targets`.
3. **CORPORATE bear case over-harsh (mechanical-only) + megacap/tech ranking tilt** (PR #15).
4. **Bear downside backstop loosened -15% -> -40%** (PR #16) — the old -15% floor was found (via `g4_sensitivity_audit.py` against real data) to reject virtually every real equity regardless of quality; real risk limiting now lives in the allocator's stress budget, not a per-name absolute veto.
5. **FX/regulatory-stress individual veto removed** (PR #17) — still computed and fed to the allocator's stress budget, but no longer an individual PASS/FAIL gate (a CEDEAR holder can hedge via canje/conversion to the underlying).
6. **Winsorize consensus low + growth-adjusted P/E cap for CORPORATE** (PR #18) — symmetric winsorization of analyst high/low targets; P/E cap now scales with growth instead of a flat 25x/30x (was structurally suppressing Bull upside for megacap/growth names like NVDA, MSFT).
7. **Widened confidence-to-Bull probability range + removed double-counted per-name margin stacking** (PR #19) — `bull_min/bull_max` widened 15-27% -> 12-32%; `minimum_margin_over_hurdle` 2% -> 0.5%; zeroed `dynamic_equity_margin`'s `base_equity_risk_buffer`/`uncertainty_buffer_max` (both were double-charging risk already priced elsewhere). **This produced the first G4_PASS candidates all session: 4/30 (DAL, NVDA, GE, MSFT).**
8. **Extended consensus bear-blend from CORPORATE to FINANCIALS/ENERGY** (PR #20) — for consistency; confirmed firing correctly on real FINANCIALS names (AXP, WFC) in production.
9. **Fase 2 cutover** (PR #21) — the big one: reordered the production pipeline so Valuation runs on the full universe *before* Research picks the Top-30, and Research selects equities by fundamentals (`value_score`) instead of technical momentum, with technical screening demoted to a binary entry-timing gate. Motivated by hard evidence: production's old technical-only Top-30 **did not even contain** the 4 tickers that pass G4 (DAL, NVDA, GE, MSFT) — the momentum/trend screen was structurally excluding exactly the names the valuation engine could validate as attractively priced.

**Validated on real production data on `main` after merge**: full chain `weekly_screening -> valuation_scenarios -> g4_cash_hurdle -> decisional_risk -> investment_committee` ran green end-to-end with **zero code changes needed downstream of Research** (g4/risk/committee untouched). Result: **4/30 G4_PASS** (DAL +3.87pp, NVDA +3.27pp, GE +1.56pp, MSFT +1.11pp above hurdle) — exact match to the shadow prediction. Committee's final decision this cycle was `HOLD_CASH_NO_ACTION` — **not a regression**, just the pre-existing fail-closed governance rule refusing to deploy while any Top-30 ticker is `BLOCKED_BY_DATA` (3/30 were this run).

## Session 2026-09-12 summary (this session)

Started from an E2E audit request: even the best G4_PASS candidates (4/30, ~9-12% risk_adjusted_er each) left the portfolio's blended return (~2.5%/yr, only ~24% of NAV ever deployed under the old risk-budget) nowhere near the ~18.6%/yr pace the $20k/24mo goal actually requires. That audit reframed the rest of the session:

1. **User redefined the mandate to a single objective** (see Objective above): reach/exceed the $ goal using available capital, with risk management serving that goal rather than competing with it, and required that new-buy proposals be evaluated against the whole current portfolio (8 real holdings: ADP, BRKB, GOOGL, RTX, SPGI, VEA, VIG, XLV), not in isolation.
2. **Data-completeness prerequisites, found while trying to risk-assess the current holdings**: a live YAML syntax bug (hotfixed immediately, was breaking all config loading), verified SEC-sourced identity fixes for PAGS (direct NYSE listing, no ADR) and UL (1:1 ADS) -- both confirmed working on real data, though PAGS separately surfaced a second bug (see open items); the ETF constituent-lookup budget (60 -> 300) that was starving IBB and likely other ETFs since the Fase 2 full-universe cutover; and `sector_overrides` for BRKB/SPGI/ADP/RTX/GOOGL, which had `industry_sector_official=None` and could never get a Bear case at all -- found a real subtlety along the way (BRKB's override needs to match its `underlying_ticker` "BRK/B", not just "BRKB"). All validated against real data before merging.
3. **`src/portfolio/allocation.py` redesigned**: `portfolio_stress_budget_nav` now conceptually covers the WHOLE portfolio (existing holdings + new buys), not new-deployment risk alone (existing_holdings_stress_nav param, not yet wired into production -- see open items); new-buy position sizing now scales with `diversification_score` (already computed against the real current holdings by `src/risk/portfolio_fit.py`) instead of every G4_PASS candidate getting the same flat per-position budget regardless of how correlated it is with what's already held. `portfolio_stress_budget_nav` raised 10% -> 30%. Confirmed on real data: the diversification multiplier correctly sizes NVDA/MSFT (higher diversification scores) up and GE (near-neutral) essentially unchanged.
4. **User flagged a further, deliberately-deferred architectural gap**: the scenario engine's 3 archetypes (CORPORATE/FINANCIALS/ENERGY) are too coarse against Comafi's real 13-category industry taxonomy -- see open items, next big topic.

## Open items for next session (updated 2026-09-12)

1. **Sector taxonomy expansion — the next big topic, by explicit user request.** Comafi exposes 13 real industry categories (Basic Materials, Communications, Consumer, Consumer Cyclical, Consumer Non-cyclical, Corp, Energy, ETF, Financial, Funds, Industrial, Technology, Utilities); the scenario engine only has 3 archetypes (CORPORATE/FINANCIALS/ENERGY), with CORPORATE as a catch-all for everything else (RTX aerospace/industrial gets the same generic EPS×PE treatment as NVDA semiconductors). Needs its own careful design pass (each new archetype needs a valuation formula tailored to that industry's real drivers -- e.g. Utilities' regulated ROE/rate-base, Industrial's backlog/margin cycles) -- do not rush this into a quick config patch.
2. **Wire `existing_holdings_stress_nav` into `build_investment_committee.py`.** The allocator (`src/portfolio/allocation.py`) now accepts it and the mechanism is tested, but production still calls it with the default 0.0 -- currently-held positions' own worst-case stress isn't yet subtracted from `portfolio_stress_budget_nav` (30%) before sizing new buys. Needs the broad-universe deep scenario review for held tickers outside this week's Top-30 to be piped into this orchestration as a new input (doesn't exist yet).
3. **Portfolio snapshot reconciliation, blocked on the user.** `data/input/portfolio_state_baseline_20260912.json` exists but is NOT wired into `portfolio_state.yml` (still points to the 20260904 baseline) because the 8 per-ticker dollar values given summed to $20,063, not the stated CEDEAR total of $19,080.36 (~$983 gap). User confirmed there's a typo on one line and will send fresh, precise data from Balanz (their broker) once account maintenance there finishes -- do not guess which number is right in the meantime.
4. **BRKB has a real, diagnosed data bug**: its `fundamental_eps_normalized` (~46,570) looks like it's sourced at BRK.A scale against a BRK.B-scale price (~$507) -- a ~1500x dual-class mismatch causing `ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH`. Not fixed -- needs a real share-class normalization mechanism (parallel to the ADR-ratio mechanism, but for domestic dual-class shares), not a guessed multiplier.
5. **PAGS has a second-order identity issue even after the ADR/direct-listing fix landed and validated correctly**: `ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH` remains, likely a currency-unit mismatch (PAGS reports fundamentals in BRL internally but trades in USD) rather than a share-ratio problem. `fundamental_fx_to_market` may need to be populated for it. Not fixed -- don't guess an FX factor without a verified source.
6. **VIG (9.34% of NAV, the largest current holding) is entirely absent from the canonical eligible universe** (`cedear_universe_master.parquet`, all ~235 tickers checked). This is a `build_universe.yml`/Comafi-catalogue gap, not a scenario-engine issue -- not investigated further this session, flagged for next time.
7. **Decide the fate of the shadow workflows** (`value_research_shadow.yml`, `value_research_shadow_g4.yml`, `src/orchestration/build_value_research_shadow.py`) — their whole purpose (compare shadow value-first vs. production technical-only) is moot now that production *is* value-first. Still not done; also disable/reconsider the Friday-22:00-UTC cron on `value_research_shadow.yml`.
8. Re-run the full chain periodically (or watch the "Weekly CEDEAR pipeline check-in" Routine, next fires 2026-09-18) to see how the PASS-candidate set evolves and to catch new data gaps over time rather than only on manual dispatch.
9. No FX/regulatory or bear-downside threshold work is pending — those are considered settled (see permanent safeguards below for why they were loosened, so they aren't re-tightened by mistake without re-running `g4_sensitivity_audit.py` first).

## Important design lessons / permanent safeguards

- Never hardcode universe size.
- Never rerun an old failed workflow expecting it to use a newer workflow definition; GitHub re-runs execute the workflow definition associated with the original run/commit.
- Manual `workflow_dispatch` of G4 chooses the latest successful Valuation run; confirm it belongs to the desired Research lineage.
- Symbol aliases are an identity-resolution problem, not merely a string-replacement problem.
- One-to-many matches must fail closed rather than be silently deduplicated.
- Research Top-30 is immutable downstream; downstream stages may classify/block candidates but must not substitute names.
- Keep `NO_NEW_DEPLOYMENT`/`HOLD_CASH_NO_ACTION` unless the full verified downstream process supports deployment.
- **A per-name absolute veto/margin is easy to justify individually but tends to duplicate a risk already priced elsewhere or already handled at the portfolio level** (this session found and fixed this pattern four separate times: Bear downside veto, FX-stress veto, `minimum_margin_over_hurdle`, `dynamic_equity_margin`'s buffers). When G4 rejects everything, check for double-counting before loosening a threshold.
- **The selection stage (which names even reach Valuation/G4) can matter more than the valuation methodology itself.** All the archetype/probability/margin fixes this session only closed part of the gap; the Fase 2 selection-order cutover is what actually produced PASS candidates, because the old technical-momentum screen was excluding the right names entirely, upstream of any G4 logic.
- `weekly_screening.yml` / `valuation_scenarios.yml` are only ever validated with full pinned lineage when run **from `main`** (their upstream-resolution steps filter `gh run list` by the triggering branch, which only matches for the actual upstream data workflows on `main`). Testing a change to these two files pre-merge is therefore limited to validating the core logic in isolation (unit tests, or a manual script invocation with hand-built fixtures) — not a full pinned dry run on a feature branch, unlike the shadow workflows (which decouple "what branch dispatches" from "what code is checked out" via a `code_ref` input specifically for this purpose).

## Do not regress to

- 316/305/304 (or any other) historical universe-size assumptions — the count is dynamic.
- deleting problematic G4/Research candidates to make 30/30 pass.
- generic token matching for BYMA/Caja identity.
- unpinned or mixed lineage between Research, Valuation, G4, Risk and Committee.
- re-tightening `max_bear_downside` back toward -15% or restoring the FX-stress individual veto without re-running `g4_sensitivity_audit.py` against current data first — both were loosened this session based on real evidence that they rejected virtually every real candidate, not because risk no longer matters (the risk is still priced, just at the portfolio/allocator level instead of a per-name absolute gate).
- reverting Research to technical/momentum-only Top-30 selection — this was the root cause of G4 never finding a candidate all session; see Fase 2 above.
