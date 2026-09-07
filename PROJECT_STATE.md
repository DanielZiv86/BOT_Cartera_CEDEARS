# BOT Cartera CEDEARS — Project State

_Last updated: 2026-09-07_

## Objective
Autonomous, professional CEDEAR portfolio-management pipeline for a 12-month investment horizon (maximum reasonable horizon 24 months), with capital preservation in USD as the primary constraint and eventual home purchase in USD as the economic objective.

The pipeline must not manufacture deployment candidates. `NO_NEW_DEPLOYMENT` remains valid unless downstream stages, using consistent lineage and verified data, justify otherwise.

## Target architecture / contract

`Comafi universe -> BYMA/Caja negotiability validation -> real eligible universe -> Research 100% -> complete ranking -> Top-30 -> Valuation 30/30 -> G4 30/30 -> Execution Gate -> Risk -> Committee`

Key rules:
- Screening is mandatory for 100% of the canonical eligible universe.
- Deep research/valuation is limited to the immutable Research Top-30.
- G4 requires Bull/Base/Bear scenarios, probabilities, net expected return, downside, costs, uncertainty penalty and explicit comparison versus cash.
- No artificial deletion/replacement of Top-30 names to force G4 success.
- Lineage must remain pinned across stages.
- Universe counts must be dynamic, never hardcoded to historical 316/305 values.
- IWDA remains an explicit mandate exception and must remain inside the universe with normal screening/scoring and traceability.

## Universe reconciliation work completed
A long reconciliation/debugging cycle was performed around the official universe and identifiers:
- baseline
- Banco Comafi catalogue
- BYMA/Caja official identity / negotiability
- inclusions
- mandate exceptions

The canonical eligible universe is currently **304 instruments**. A previous 305-instrument universe contained false-positive/stale eligibility and therefore downstream Research/Valuation/G4 based on 305 became obsolete.

The Universe Gate eventually passed with the corrected canonical universe.

## Current E2E lineage

### Universe
- Current canonical eligible count: **304**
- Universe Gate: PASS on the corrected lineage.

### Research
A new Research run was manually triggered after the universe was corrected.
- Run: `34159055890`
- Result: PASS
- Expected contract: **304/304 Research coverage** and immutable Top-30.

### Valuation
The old valuation workflow contained a hardcoded `assert len(r) == 305` and historical 305 assumptions.

This was corrected so counts derive dynamically from `canonical_eligible_count` / actual Top-N instead of fixed 305/316 values.

The new Research lineage successfully produced a valid new Valuation run/artifact.
- Valuation run consumed by current G4: `34159086076`
- Contract validated in G4 download step: Top-N = 30, valuation_count = 30, valuation parquet = 30 rows, valuation tickers = immutable Research Top-30.

### G4
Initial G4 failure showed cross-layer symbol identity mismatches in `portfolio_fit_quantitative.parquet`:
- `BA.C` vs `BA`
- `BBV` vs `BBVA`
- `TRVV` vs `TRV`

Commit `0a792f58ba0e53fedb9303419bfc601770c4330d` added normalization for those identities.

Manual G4 run:
- Run: `34159513239`
- Job: `101858201194`
- Workflow number: Build Valuation G4 Cash Hurdle #138
- Result: FAILED

The failure is **not** missing Top-30 identities anymore. The exact current failure is:

`AssertionError: ('data/upstream_local/cedear_local_market.parquet', 31)`

Reason: after alias normalization, the local-market layer returns 31 rows for 30 Top-N identities. At least one normalized identity has multiple upstream rows. A simple normalized `isin()` filter therefore violates the required one-to-one Top-30 contract.

The current lineage pinned by that G4 run was:
- Valuation run: `34159086076`
- Local Market run: `34158337936`
- Portfolio State run: `34138776023`

G4 unit tests themselves passed: **8/8**.

## Latest fix applied
Commit:
- `45a8f57e0ed761829aae9e324626628f5ed4e8dd`

File:
- `.github/workflows/g4_cash_hurdle.yml`

The G4 candidate restriction was changed from a bulk normalized `isin()` filter to strict deterministic **one Research Top-30 identity -> one upstream row** resolution:
1. Prefer exact raw ticker match.
2. Only use alias-equivalent match as fallback.
3. Fail explicitly if fallback is ambiguous.
4. Do not reuse the same upstream row for two Research candidates.
5. Preserve the Research ticker as canonical output identity.
6. Assert exactly 30 rows and exactly the immutable Top-30.

This intentionally avoids `drop_duplicates`, because silently dropping duplicates could hide a real identity problem and alter economic lineage.

## Exact next action
Run manually from `main`:

**Build Valuation G4 Cash Hurdle**

This new run must use commit `45a8f57e...` or later.

Then inspect G4 before advancing. Do **not** rerun Research or Valuation unless G4 proves an upstream lineage/data inconsistency.

If G4 passes, validate:
- 30/30 candidates accounted for
- evaluated + blocked = 30
- no artificial Top-30 mutation
- execution-ready / not-execution-ready classification economically justified
- G4 cash hurdle remains intact

Only after G4 is valid continue:

`Execution Gate -> Risk -> Committee`

Do not advance Risk/Committee on a broken or inconsistent G4 lineage.

## Important design lessons / permanent safeguards
- Never hardcode universe size.
- Never rerun an old failed workflow expecting it to use a newer workflow definition; GitHub re-runs execute the workflow definition associated with the original run/commit.
- Manual `workflow_dispatch` of G4 chooses the latest successful Valuation run; confirm it belongs to the desired Research lineage.
- Symbol aliases are an identity-resolution problem, not merely a string-replacement problem.
- One-to-many matches must fail closed rather than be silently deduplicated.
- Research Top-30 is immutable downstream; downstream stages may classify/block candidates but must not substitute names.
- Keep `NO_NEW_DEPLOYMENT` unless the full verified downstream process supports deployment.

## Relevant recent commits
- `d131321b` — removed historical fixed 305 assumptions from Valuation and made universe/Top-N counts dynamic.
- `0a792f58ba0e53fedb9303419bfc601770c4330d` — first G4 alias normalization for BA.C/BA, BBV/BBVA, TRVV/TRV.
- `45a8f57e0ed761829aae9e324626628f5ed4e8dd` — strict one-to-one Top-30 identity resolution in G4 candidate layers; current head/fix to validate next.

## Do not regress to
- 316 historical universe assumptions.
- 305 historical universe assumptions.
- deleting problematic G4 tickers to make 30/30 pass.
- generic token matching for BYMA/Caja identity.
- unpinned or mixed lineage between Research, Valuation, G4, Risk and Committee.
