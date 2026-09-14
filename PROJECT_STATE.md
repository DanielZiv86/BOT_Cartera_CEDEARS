# BOT Cartera CEDEARS — Project State

_Last updated: 2026-09-12 (end of session)_

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
5. **User questioned the `BLOCKED_BY_DATA` governance rule** ("¿por qué bloqueamos la asignación si hay un BLOCKED_BY_DATA? ¿un experto no sacaría ese ticker del Top-30 y listo?"). Investigation found this was a REAL bug, not just a design question: the veto was independently duplicated in **three** layers -- `build_g4_cash_hurdle.py::_govern` (`deployment_decision='NO_NEW_DEPLOYMENT_DATA_GAPS'` whenever `blocked_count>0`, checked *before* whether any clean G4_PASS candidate existed), `build_decisional_risk.py` (its own standalone `blocked_count>0` veto, redundant with G4's), and `build_investment_committee.py` (`elif blocked>0: HOLD_CASH_NO_ACTION` as a decision-terminal branch). All three fixed: a blocked ticker (a per-ticker data gap, e.g. PAGS's currency-normalization bug) is excluded from evaluation on its own -- as it always was -- but no longer vetoes deployment into other, cleanly-evaluated G4_PASS candidates. `ranking_status`/`secondary_considerations` still surface the gap for visibility. Methodology versions bumped: G4 unchanged (G4-2.1, only the governance wrapper changed, not the economic engine), Risk RISK-DECISIONAL-1.3 -> 1.4, Committee COMMITTEE-1.2 -> 1.3.
6. **Wired `existing_holdings_stress_nav` into production** (was the top open item from earlier in this session). New `_compute_existing_holdings_stress()` in `build_investment_committee.py` runs Deep Scenario Review against the broad-universe valuation (not just this week's Top-30) for every currently-held ticker, sums `weight * |bear-case % move|` for tickers whose scenario validates, and reports unassessed held tickers' weight separately (never defaults their risk to zero). `investment_committee.yml` now downloads `canonical-broad-valuation-scenarios` (via `research_run_id` from the same `weekly_screening.yml` run) and passes `--positions`/`--broad-valuation`/`--scenario-policy`.

**Both fixes validated together on real market data**, dispatched on the feature branch (`weekly_screening.yml` -> `valuation_scenarios.yml` with `dispatch_g4=true` -> G4 -> Risk -> Committee, all green, `FINAL_E2E: PASS`). Before today's fix, this exact week's data (PAGS still `BLOCKED_BY_DATA`, its currency bug unfixed) would have produced `HOLD_CASH_NO_ACTION` / `SCENARIO_DATA_GAPS_FAIL_CLOSED` regardless of anything else. After: **4/30 G4_PASS (NVDA, GE, MSFT, AMZN)**, PAGS still individually `BLOCKED_BY_DATA` (reported in `secondary_considerations`, no longer a veto), Committee decision **`CANDIDATES_REQUIRE_EXECUTION_GATE` / `G4_PASS_RISK_PASS`** -- the allocator actually executed for the first time this session:

| ticker | target_weight | diversification_multiplier | worst_case_stress_loss |
|---|---|---|---|
| NVDA | 7.30% | 1.1666 | 31.9% |
| MSFT | 6.81% | 1.1325 | 33.3% |
| AMZN | 6.09% | 1.0534 | 34.6% |
| GE | 5.88% | 0.9762 | 33.2% |

Portfolio-wide stress accounting: `existing_holdings_stress_contribution_nav`=6.17% (from the 6 currently-held positions Deep Scenario Review could actually assess: ADP/GOOGL/RTX/SPGI/VEA/XLV; BRKB and VIG remain unassessed -- see open items 4/6 -- and their 15.47% combined NAV weight is reported, not silently zeroed), `new_deployment_stress_contribution_nav`=8.66%, `total_portfolio_stress_contribution_nav`=14.83% vs. the 30% budget (`portfolio_stress_budget_ok: true`, real headroom remained). `goal_tracking`: required 18.65%/yr, this cycle's weighted new-deployment expected return 10.28%/yr -- still `NEW_DEPLOYMENT_BELOW_PACE` (expected; these were governance/wiring fixes, not new G4_PASS candidates or a threshold change, so they were never going to close the whole gap on their own).

Also discovered, and corrected in `PROJECT_STATE.md` itself: the "only validates with pinned lineage from `main`" note below was too pessimistic -- `weekly_screening.yml`/`valuation_scenarios.yml`'s upstream lookups are branch-scoped, but the upstream workflows themselves (`build_universe.yml`, `underlying_prices.yml`, `market_features.yml`, `cedear_local_market.yml`, `portfolio_state.yml`) are plain `workflow_dispatch` with no required inputs and (except `underlying_prices.yml`'s own dependency on `build_universe.yml`, and `market_features.yml`'s on `underlying_history.yml`, neither of which are branch-scoped either) no cross-branch requirements. Dispatching all 5 on the feature branch once unblocks a fully real, pinned-lineage dry run pre-merge without needing `main` at all.

## Open items for next session (updated 2026-09-12)

1. **Sector taxonomy expansion — the next big topic, by explicit user request.** Comafi exposes 13 real industry categories (Basic Materials, Communications, Consumer, Consumer Cyclical, Consumer Non-cyclical, Corp, Energy, ETF, Financial, Funds, Industrial, Technology, Utilities); the scenario engine only has 3 archetypes (CORPORATE/FINANCIALS/ENERGY), with CORPORATE as a catch-all for everything else (RTX aerospace/industrial gets the same generic EPS×PE treatment as NVDA semiconductors). Needs its own careful design pass (each new archetype needs a valuation formula tailored to that industry's real drivers -- e.g. Utilities' regulated ROE/rate-base, Industrial's backlog/margin cycles) -- do not rush this into a quick config patch.
2. ~~Wire `existing_holdings_stress_nav` into `build_investment_committee.py`~~ **DONE this session**, validated on real data (see summary above).
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
- `weekly_screening.yml` / `valuation_scenarios.yml` resolve their upstreams (`build_universe.yml`, `market_features.yml`, `underlying_prices.yml`, `cedear_local_market.yml`, `portfolio_state.yml`) filtered by the triggering branch (`gh run list --branch "${GITHUB_REF_NAME}"`) — so a feature branch that never had its own successful runs of those five will fail with `ValueError: invalid literal for int() with base 10: ''` (an empty run id). **This is not a `main`-only limitation** (corrected 2026-09-12; an earlier version of this note said otherwise): all five are plain `workflow_dispatch` with no required inputs, so dispatching them once on the feature branch (in any order — the ones with their own upstream dependencies, `underlying_prices.yml` on `build_universe.yml` and `market_features.yml` on `underlying_history.yml`, resolve those via an unfiltered `gh run list`, i.e. latest successful run on ANY branch) unblocks a fully real, pinned-lineage dry run of the whole production chain pre-merge, without needing `main` at all.

## Do not regress to

- 316/305/304 (or any other) historical universe-size assumptions — the count is dynamic.
- deleting problematic G4/Research candidates to make 30/30 pass.
- generic token matching for BYMA/Caja identity.
- unpinned or mixed lineage between Research, Valuation, G4, Risk and Committee.
- re-tightening `max_bear_downside` back toward -15% or restoring the FX-stress individual veto without re-running `g4_sensitivity_audit.py` against current data first — both were loosened this session based on real evidence that they rejected virtually every real candidate, not because risk no longer matters (the risk is still priced, just at the portfolio/allocator level instead of a per-name absolute gate).
- reverting Research to technical/momentum-only Top-30 selection — this was the root cause of G4 never finding a candidate all session; see Fase 2 above.
