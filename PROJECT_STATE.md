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

## Open items for next session

1. **Investigate the 3 `BLOCKED_BY_DATA` tickers** in the most recent real Committee run — this is currently the only thing standing between "4 real G4_PASS candidates" and an actual deployment decision. Pull the latest `investment_committee.yml`/`g4_cash_hurdle.yml` artifact on `main`, find which 3 tickers blocked and why (missing analyst coverage, stale price target, sector unverified, etc.), and decide whether it's a data-source gap or a policy fail-closed appropriately.
2. **Decide the fate of the shadow workflows** (`value_research_shadow.yml`, `value_research_shadow_g4.yml`, `src/orchestration/build_value_research_shadow.py`) — their whole purpose (compare shadow value-first vs. production technical-only) is moot now that production *is* value-first. Flagged in PR #21 as optional post-cutover housekeeping, not done yet. Also disable/reconsider the Friday-22:00-UTC cron on `value_research_shadow.yml` (added in PR #14 specifically to build evidence for the Fase 2 decision, which is now made).
3. **FINANCIALS/ENERGY still lack a growth-adjusted-cap-equivalent fix.** Deliberately not extended this session (doesn't map cleanly: FINANCIALS is P/B-based and already ROE-sensitive via `fair_pb`; ENERGY is already cyclically earnings/FCF-normalized). Revisit only if a real FINANCIALS/ENERGY name is later found stuck on a similar flat-cap distortion the way NVDA/MSFT were for CORPORATE.
4. **Re-run the full chain periodically** (or set up a Routine) now that the pipeline is live, to see how the 4-PASS-candidate set evolves as prices/consensus targets move, and to catch the data gaps in item 1 over time rather than only on manual dispatch.
5. No FX/regulatory or bear-downside threshold work is pending — those are considered settled for now (see permanent safeguards below for why they were loosened, so they aren't re-tightened by mistake without re-running `g4_sensitivity_audit.py` first).

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
