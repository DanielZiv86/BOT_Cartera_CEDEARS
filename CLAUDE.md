# BOT_Cartera_CEDEARS — instructions for Claude

Autonomous CEDEAR portfolio pipeline for Daniel (danielzivkovich@gmail.com). Single mandate: reach or exceed $20,000 additional USD by 2028-09-11 (24-month horizon), using the capital available. Risk management (G4 Bear discipline, correlation-awareness, fail-closed data handling) exists to serve that goal reliably, not as a competing "preserve capital first" constraint -- see PROJECT_STATE.md's Objective section for the full framing.

**Read `PROJECT_STATE.md` first, every session.** It has the current pipeline architecture, what changed most recently, and the open items to pick up next — this file only has the standing rules that don't change session to session.

## Standing operational rules

- **Never push to `main` without explicit per-PR approval from the user.** Always: branch -> PR -> present findings -> get an explicit yes -> merge. A prior approval does not carry over to later PRs.
- **Validate any economic/policy change against real market data before opening a PR**, via the GitHub Actions shadow chain (`value_research_shadow.yml` with `dispatch_g4=true`, or the real production workflows once you're validating post-cutover behavior — see the "pinned lineage" note in `PROJECT_STATE.md`). Quote the before/after numbers in the PR body.
- **Run the full `pytest -q` suite before every commit.** Exactly 2 pre-existing failures are expected and unrelated: `tests/test_broad_etf_aggregate_fallback.py::test_broad_etf_uses_fresh_aggregate_consensus_without_relaxing_lookthrough_gate` and `::test_broad_etf_remains_blocked_when_no_independent_aggregate_evidence_exists` (confirmed via `git stash` — pre-existing on `main`, not introduced by session work). Never "fix" these as a side effect of unrelated work; if you genuinely need to fix them, do it as its own explicit, flagged change.
- **Never hardcode the universe size or Top-N count.** It's dynamic; treat any literal 30/235/304/305/316 found outside test fixtures as suspect.
- Clean `__pycache__` before every commit (`find . -name "__pycache__" -exec rm -rf {} +`).
- When a per-name individual veto/margin makes G4 reject almost everything, suspect double-counting (a risk already priced in the scenario return, or already handled at the portfolio/allocator level) before loosening the threshold. This exact pattern has been found and fixed four times already this project — see `PROJECT_STATE.md`'s permanent safeguards.

## Where things live

- `src/valuation/deep_scenario_engine.py` — sector-aware Bull/Base/Bear scenario engine (CORPORATE/FINANCIALS/ENERGY archetypes), consensus winsorization, dynamic probabilities.
- `src/valuation/g4.py` + `src/orchestration/build_g4_cash_hurdle.py` — G4 Cash Hurdle (the "does this clear cash by enough to be worth the risk" gate).
- `src/research/screening.py` (technical) / `src/research/value_screening.py` (fundamentals) / `src/research/ranking.py` (`build_ranking` technical-only, `build_value_ranking` current production value-first two-track ranking) — Research/Top-30 selection.
- `src/orchestration/build_value_research_screening.py` — current production Research entrypoint (value-first). `src/orchestration/build_research_screening.py` (technical-only) is no longer used in production as of the Fase 2 cutover, kept only as the historical/simpler pattern `integrity_report` was adapted from.
- `src/portfolio/allocation.py` — risk-budget rank-fill allocator (ranks G4_PASS by `risk_adjusted_er`).
- `src/portfolio/goals.py` — goal-tracking pace vs. the $ objective (informational only, never gates).
- `config/*.yml` — all the policy knobs above are config-driven; `policy_notes` lists in each file explain *why* a value is what it is, keep them accurate when you change a value.
- `.github/workflows/weekly_screening.yml` -> `valuation_scenarios.yml` -> `g4_cash_hurdle.yml` -> `decisional_risk.yml` -> `investment_committee.yml` — the real production chain, auto-chained via `gh workflow run` at the end of each step. Only ever fully validates with pinned lineage when dispatched from `main`.
