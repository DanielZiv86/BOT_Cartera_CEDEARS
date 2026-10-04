# Archived GitHub Actions workflows (removed 2026-10-04)

**Why this file exists**: on 2026-10-04 all 18 GitHub Actions workflow files under
`.github/workflows/` were deleted from this repo at Daniel's explicit request, to free
up GitHub Actions capacity (concurrent job slots / minutes) for a different project on
the same account. This was **not** a decision that the pipeline was wrong or finished —
at the time of removal the pipeline was fully working end-to-end on real market data,
running autonomously every Friday via a scheduled Routine (see `PROJECT_STATE.md`'s
session history for the full track record). This file is the full backup of every
workflow's content so the automation can be reconstructed later, here or in another
project, without having to re-derive any of this design from scratch.

Each workflow below is reproduced verbatim as it existed on `main` immediately before
deletion (commit before `remove .github/workflows` on 2026-10-04). To restore one,
recreate `.github/workflows/<name>.yml` with the content shown and re-add any secrets
it references (`FINNHUB_TOKEN`, `IOL_USERNAME`, `IOL_PASSWORD`) in the target repo's
Settings -> Secrets and variables -> Actions.

## Production chain, execution order

The 9 workflows that made up the real weekly production pipeline, in dependency order
(each downloads the prior stage's artifact and is pinned to the same git ref):

```
build_universe.yml
  -> underlying_prices.yml, underlying_history.yml (both depend on build_universe.yml)
    -> market_features.yml (depends on underlying_history.yml)
    -> risk_correlations.yml (depends on underlying_history.yml)
    -> cedear_local_market.yml (depends on build_universe.yml, underlying_prices.yml)
    -> portfolio_state.yml (depends on underlying_history.yml, risk_correlations.yml)
      -> weekly_screening.yml (depends on build_universe.yml, market_features.yml, underlying_prices.yml)
        -> valuation_scenarios.yml (depends on weekly_screening.yml; dispatch_g4=true auto-chains the rest)
          -> g4_cash_hurdle.yml
            -> decisional_risk.yml
              -> investment_committee.yml
```

`bootstrap.yml` and `daily_market_data.yml` were early scaffolding, superseded by the
real pipeline above (kept for historical reference, never removed earlier because they
were harmless placeholders). `e2e_autonomous_certification.yml` was a meta-workflow
that dispatched and certified the entire chain in one shot with pinned lineage.
`g4_v22_shadow_audit_launcher.yml`, `g4_v22_portfolio_stress_launcher.yml` and
`scenario_v23_sensitivity_audit.yml` were audit-only launchers for an experimental
G4-2.2/Scenario-2.3 methodology that lives on the separate, never-merged branch
`audit/scenario-v2-3-probabilistic-bear` — they never had production decision
authority and never touched Risk/Committee/order dispatch.

---

## bootstrap.yml

Earliest scaffold: checks out the repo, installs deps, runs the full `pytest -q`
suite as a smoke test. Superseded by the real pipeline below but kept as a quick
sanity-check workflow.

```yaml
name: Bootstrap Environment

on:
  workflow_dispatch:

jobs:
  bootstrap:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run smoke tests
        run: pytest -q

      - name: Placeholder summary
        run: echo "Bootstrap scaffold validated. Heavy data logic is not enabled yet."
```

---

## daily_market_data.yml

Early placeholder for a daily market-data job that was never implemented beyond the
scaffold (no real connector wired in).

```yaml
name: Daily Market Data Placeholder

on:
  workflow_dispatch:
  schedule:
    # Placeholder: 21:30 UTC ~= 18:30 Argentina (UTC-3)
    - cron: '30 21 * * 1-5'

jobs:
  daily-market-data:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Placeholder only
        run: |
          echo "Daily market-data workflow scaffold is active."
          echo "No external market-data acquisition is implemented yet."
```

---

## build_universe.yml

Stage 1 of the real pipeline. Builds the canonical CEDEAR universe from Comafi's
source catalogue, reconciles against BYMA/Caja de Valores live negotiability, applies
geography eligibility, mandate exclusions/inclusions and symbol aliasing, and emits
`cedear_universe_master.parquet` + `security_symbol_map.parquet`. Gated by a hard
"Universe V2.1 Gate" assertion (`universe_gate_status=PASS`, no missing mandate
exceptions, symbol-map count matches eligible count).

```yaml
name: Build Universe Master and Symbol Map

on:
  workflow_dispatch:
  push:
    paths:
      - "data/input/CEDEAR_Universe_Master_v2.json"
      - "src/universe/**"
      - "src/connectors/finnhub.py"
      - "src/orchestration/build_universe.py"
      - "src/orchestration/diagnose_universe_sources.py"
      - "config/symbol_aliases.yml"
      - "config/mandate_exclusions.yml"
      - "config/universe_inclusions.yml"
      - "config/geography_eligibility.yml"
      - "tests/test_universe.py"
      - "requirements.txt"
      - ".github/workflows/build_universe.yml"

jobs:
  build-universe:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      FINNHUB_TOKEN: ${{ secrets.FINNHUB_TOKEN }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -q tests/test_universe.py
      - name: Check canonical source exists
        run: test -f data/input/CEDEAR_Universe_Master_v2.json || (echo "Missing canonical source" && exit 2)
      - name: Diagnose official sources
        run: python -m src.orchestration.diagnose_universe_sources
      - name: Build, reconcile and geography-filter official universe
        run: |
          python -m src.orchestration.build_universe \
            --input data/input/CEDEAR_Universe_Master_v2.json \
            --aliases config/symbol_aliases.yml \
            --exclusions config/mandate_exclusions.yml \
            --inclusions config/universe_inclusions.yml \
            --geography-policy config/geography_eligibility.yml \
            --output-dir data/canonical
      - name: Enforce Universe V2.1 Gate
        run: |
          python - <<'PY'
          import json
          m=json.load(open('data/canonical/universe_manifest.json'))
          assert m['universe_gate_status']=='PASS', m
          assert m['geography_accounting_status']=='PASS', m
          assert m.get('official_reconciliation_blocking_count',0)==0, m
          assert not m['mandate_exceptions_missing'], m
          assert m['canonical_eligible_count']==m['symbol_map_count'], m
          assert m['canonical_eligible_count']>0, m
          assert m['canonical_eligible_count'] < m['official_pre_geography_eligible_count'], 'V2.1 geography mandate did not remove any instrument'
          print('UNIVERSE_V2_1_GATE_PASS',m['canonical_eligible_count'],'geography_excluded=',m['geography_excluded_count'])
          PY
      - name: Upload universe diagnostics and artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: canonical-universe
          path: |
            data/canonical/universe_source_diagnostics.json
            data/canonical/cedear_universe_master.json
            data/canonical/cedear_universe_master.parquet
            data/canonical/cedear_geography_exclusions.json
            data/canonical/cedear_mandate_exclusions.json
            data/canonical/cedear_universe_inclusions.json
            data/canonical/cedear_official_reconciliation_unresolved.json
            data/canonical/security_symbol_map.json
            data/canonical/security_symbol_map.parquet
            data/canonical/universe_manifest.json
          if-no-files-found: warn
```

---

## underlying_prices.yml

Builds current underlying-equity prices for everything in the canonical symbol map.
Scheduled daily (22:30 UTC weekdays) in addition to manual/push dispatch.

```yaml
name: Build Underlying Price Layer

on:
  workflow_dispatch:
  schedule:
    - cron: "30 22 * * 1-5"
  push:
    paths:
      - "src/connectors/**"
      - "src/market_data/**"
      - "src/orchestration/build_underlying_prices.py"
      - "tests/test_underlying_prices.py"
      - ".github/workflows/underlying_prices.yml"

permissions:
  contents: read
  actions: read

jobs:
  build-underlying-prices:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_underlying_prices.py tests/test_universe.py
      - name: Download latest canonical security symbol map
        run: |
          RUN_ID=$(gh run list --workflow build_universe.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          test -n "$RUN_ID" && test "$RUN_ID" != "null"
          echo "Using canonical universe workflow run: $RUN_ID"
          mkdir -p data/upstream_universe
          gh run download "$RUN_ID" --name canonical-universe --dir data/upstream_universe
          test -f data/upstream_universe/security_symbol_map.json
      - name: Build Underlying Price Layer
        run: python -m src.orchestration.build_underlying_prices --symbol-map data/upstream_universe/security_symbol_map.json --output-dir data/canonical/market_data
      - uses: actions/upload-artifact@v4
        with:
          name: underlying-price-layer
          path: |
            data/canonical/market_data/underlying_prices.json
            data/canonical/market_data/underlying_prices.parquet
            data/canonical/market_data/underlying_price_metrics.json
          if-no-files-found: error
          retention-days: 90
```

---

## underlying_history.yml

Builds historical price series for everything in the symbol map plus every current
real holding, and hard-fails if any current holding lacks usable history. Scheduled
daily (23:00 UTC weekdays).

```yaml
name: Build Underlying Historical Price Layer

on:
  workflow_dispatch:
  schedule:
    - cron: "0 23 * * 1-5"
  push:
    paths:
      - "src/market_data/history_layer.py"
      - "src/orchestration/build_underlying_history.py"
      - "data/input/portfolio_state_*.json"
      - "tests/test_underlying_history.py"
      - ".github/workflows/underlying_history.yml"

permissions:
  contents: read
  actions: read

jobs:
  build-underlying-history:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_underlying_history.py tests/test_underlying_prices.py tests/test_universe.py
      - name: Download latest canonical security symbol map
        run: |
          RUN_ID=$(gh run list --workflow build_universe.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          test -n "$RUN_ID" && test "$RUN_ID" != "null"
          mkdir -p data/upstream_universe
          gh run download "$RUN_ID" --name canonical-universe --dir data/upstream_universe
          test -f data/upstream_universe/security_symbol_map.json
      - name: Build Underlying Historical Price Layer
        run: |
          python -m src.orchestration.build_underlying_history --symbol-map data/upstream_universe/security_symbol_map.json --portfolio-state data/input/portfolio_state_baseline_20260914.json --universe-input data/input/CEDEAR_Universe_Master_v2.json --aliases config/symbol_aliases.yml --output-dir data/canonical/market_data --max-workers 12
      - name: Verify every current holding has usable history
        run: |
          python - <<'PY'
          import json, pandas as pd
          p=json.load(open('data/input/portfolio_state_baseline_20260914.json'))
          holdings={str(x['cedear_ticker']).upper() for x in p['positions'] if float(x.get('weight',0))>0}
          s=pd.read_parquet('data/canonical/market_data/underlying_history_status.parquet')
          usable=set(s.loc[s['history_status'].isin(['HISTORY_READY','SHORT_HISTORY_BY_AGE']),'cedear_ticker'].astype(str).str.upper())
          missing=sorted(holdings-usable); assert not missing, f'CURRENT_HOLDING_HISTORY_BLOCKED: {missing}'
          print('CURRENT_HOLDING_HISTORY_READY', sorted(holdings))
          PY
      - uses: actions/upload-artifact@v4
        with:
          name: underlying-history-layer
          path: |
            data/canonical/market_data/underlying_history.parquet
            data/canonical/market_data/underlying_history_status.json
            data/canonical/market_data/underlying_history_status.parquet
            data/canonical/market_data/underlying_history_metrics.json
          if-no-files-found: error
          retention-days: 90
```

---

## market_features.yml

Builds technical/market feature engine from the historical price layer.

```yaml
name: Build Market Feature Engine

on:
  workflow_dispatch:
  push:
    paths:
      - "src/features/**"
      - "src/orchestration/build_market_features.py"
      - "tests/test_market_features.py"
      - ".github/workflows/market_features.yml"

permissions:
  contents: read
  actions: read

jobs:
  build-market-features:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_market_features.py
      - name: Download latest underlying history artifact
        run: |
          RUN_ID=$(gh run list --workflow underlying_history.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          test -n "$RUN_ID" && test "$RUN_ID" != "null"
          mkdir -p data/upstream_history
          gh run download "$RUN_ID" --name underlying-history-layer --dir data/upstream_history
          test -f data/upstream_history/underlying_history.parquet
      - name: Build Market Feature Engine
        run: python -m src.orchestration.build_market_features --history data/upstream_history/underlying_history.parquet --output-dir data/canonical/features
      - uses: actions/upload-artifact@v4
        with:
          name: market-feature-engine
          path: |
            data/canonical/features/market_features.json
            data/canonical/features/market_features.parquet
            data/canonical/features/market_feature_metrics.json
          if-no-files-found: error
          retention-days: 90
```

---

## risk_correlations.yml

Builds the risk/correlation engine (correlation matrix, rolling correlations vs.
SPY benchmark) from the historical price layer.

```yaml
name: Build Risk and Correlation Engine

on:
  workflow_dispatch:

permissions:
  contents: read
  actions: read

jobs:
  build-risk-correlations:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_risk_engine.py
      - name: Download latest underlying history artifact
        run: |
          RUN_ID=$(gh run list --workflow underlying_history.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          test -n "$RUN_ID" && test "$RUN_ID" != "null"
          mkdir -p data/upstream_history
          gh run download "$RUN_ID" --name underlying-history-layer --dir data/upstream_history
          test -f data/upstream_history/underlying_history.parquet
      - name: Build Risk and Correlation Engine
        run: python -m src.orchestration.build_risk_correlations --history data/upstream_history/underlying_history.parquet --benchmark SPY --output-dir data/canonical/risk
      - uses: actions/upload-artifact@v4
        with:
          name: risk-correlation-engine
          path: |
            data/canonical/risk/risk_metrics.json
            data/canonical/risk/risk_metrics.parquet
            data/canonical/risk/correlation_matrix_long.parquet
            data/canonical/risk/rolling_correlations.parquet
            data/canonical/risk/risk_engine_metrics.json
          if-no-files-found: error
          retention-days: 90
```

---

## cedear_local_market.yml

Builds the local BYMA CEDEAR market layer (ARS quotes, implied CCL) from the
universe + underlying prices. Scheduled daily (19:30 UTC weekdays). Requires
`IOL_USERNAME`/`IOL_PASSWORD` secrets (IOL Inversiones broker connector).

```yaml
name: Build CEDEAR Local Market Layer

on:
  workflow_dispatch:
  schedule:
    - cron: "30 19 * * 1-5"
  push:
    branches: [main]
    paths:
      - "src/connectors/iol.py"
      - "src/connectors/data912.py"
      - "src/connectors/comafi.py"
      - "src/market_data/cedear_local.py"
      - "src/market_data/local_market_recovery.py"
      - "src/market_data/local_market_diagnostics.py"
      - "src/orchestration/build_cedear_local_market.py"
      - "tests/test_cedear_local_market.py"
      - "tests/test_local_market_recovery.py"
      - ".github/workflows/cedear_local_market.yml"
permissions:
  contents: read
  actions: read
jobs:
  build-cedear-local-market:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
      IOL_USERNAME: ${{ secrets.IOL_USERNAME }}
      IOL_PASSWORD: ${{ secrets.IOL_PASSWORD }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_cedear_local_market.py tests/test_local_market_recovery.py
      - name: Download serialized upstreams
        run: |
          U=$(gh run list --workflow build_universe.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'); P=$(gh run list --workflow underlying_prices.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$U" && test -n "$P"
          mkdir -p data/upstream_universe data/upstream_prices
          gh run download "$U" --name canonical-universe --dir data/upstream_universe
          gh run download "$P" --name underlying-price-layer --dir data/upstream_prices
      - name: Build local CEDEAR market and implied CCL
        run: python -m src.orchestration.build_cedear_local_market --universe data/upstream_universe/cedear_universe_master.parquet --underlying-prices data/upstream_prices/underlying_prices.parquet --output-dir data/canonical/local_market --brokerage-rate 0.006
      - uses: actions/upload-artifact@v4
        with:
          name: cedear-local-market-layer
          path: data/canonical/local_market/
          if-no-files-found: error
          retention-days: 90
```

---

## portfolio_state.yml

Builds the real portfolio-state engine (NAV, positions, quantitative portfolio fit)
from the real holdings baseline file plus the history/risk layers.

```yaml
name: Build Portfolio State Engine

on:
  workflow_dispatch:

permissions:
  contents: read
  actions: read

jobs:
  build-portfolio-state:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_portfolio_state.py tests/test_risk_engine.py
      - name: Download latest upstream artifacts
        run: |
          H=$(gh run list --workflow underlying_history.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$H" && test "$H" != "null"
          Q=$(gh run list --workflow risk_correlations.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$Q" && test "$Q" != "null"
          mkdir -p data/upstream_history data/upstream_risk
          gh run download "$H" --name underlying-history-layer --dir data/upstream_history
          gh run download "$Q" --name risk-correlation-engine --dir data/upstream_risk
      - name: Build Portfolio State Engine
        run: python -m src.orchestration.build_portfolio_state --portfolio-state data/input/portfolio_state_baseline_20260914.json --history data/upstream_history/underlying_history.parquet --correlations data/upstream_risk/correlation_matrix_long.parquet --classification config/portfolio_classification.yml --output-dir data/canonical/portfolio
      - name: Enforce quantitative Portfolio Fit contract
        run: |
          python - <<'PY'
          import json,pandas as pd
          m=json.load(open('data/canonical/portfolio/portfolio_state_manifest.json')); assert m['portfolio_risk']['portfolio_risk_status']=='PORTFOLIO_RISK_READY',m
          f=pd.read_parquet('data/canonical/portfolio/portfolio_fit_quantitative.parquet'); assert (f['portfolio_fit_status']=='PORTFOLIO_FIT_QUANT_READY').all(); assert (f['portfolio_weight_covered']>=.95).all()
          print('PORTFOLIO_FIT_QUANT_READY',len(f))
          PY
      - uses: actions/upload-artifact@v4
        with:
          name: portfolio-state-engine
          path: data/canonical/portfolio/
          if-no-files-found: error
          retention-days: 90
```

---

## weekly_screening.yml ("Build Research MVP Screening")

Stage: full-universe Valuation + value-first Research Top-30 selection (Fase 2
cutover, 2026-09-11). Runs Valuation (Bull/Base/Bear scenario engine) over the
*entire* canonical universe first, then Research ranks by `value_score`
(fundamentals) with technical screening demoted to a binary entry-timing gate, and
selects the immutable Top-30 that everything downstream consumes.

```yaml
name: Build Research MVP Screening

# Fase 2: Valuation now runs here, over the FULL canonical universe, before
# Research picks the Top-N -- equities are selected by value_score
# (fundamentals), with the existing technical screening_score used only as a
# binary entry-timing gate. ETFs/non-equity keep their own reserved,
# technical-only ranked slots. The shadow comparison that motivated this
# cutover (value_research_shadow.yml, retired 2026-09-14 once production
# itself became value-first) is documented in PROJECT_STATE.md.

on:
  workflow_dispatch:
  push:
    paths:
      - "src/research/**"
      - "src/orchestration/build_value_research_screening.py"
      - "src/orchestration/build_valuation_scenarios.py"
      - "config/value_screening_policy.yml"
      - "config/valuation_policy.yml"
      - "tests/test_research_screening.py"
      - "tests/test_value_screening.py"
      - "tests/test_ranking_value_first.py"
      - "tests/test_build_value_research_screening.py"
      - ".github/workflows/weekly_screening.yml"

concurrency:
  group: weekly-screening-main
  cancel-in-progress: true
permissions:
  contents: read
  actions: read

jobs:
  weekly-screening:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
      FINNHUB_TOKEN: ${{ secrets.FINNHUB_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q tests/test_research_screening.py tests/test_value_screening.py tests/test_ranking_value_first.py tests/test_build_value_research_screening.py tests/test_valuation_engines.py tests/test_valuation_v17.py tests/test_finnhub_symbol_normalization.py tests/test_vanguard_holdings_parser.py
      - name: Download serialized upstreams from same ref
        run: |
          U=$(gh run list --workflow build_universe.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$U" && test "$U" != null
          F=$(gh run list --workflow market_features.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$F" && test "$F" != null
          Q=$(gh run list --workflow underlying_prices.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$Q" && test "$Q" != null
          echo "UNIVERSE_RUN_ID=$U" >> "$GITHUB_ENV"
          echo "FEATURE_RUN_ID=$F" >> "$GITHUB_ENV"
          echo "PRICE_RUN_ID=$Q" >> "$GITHUB_ENV"
          mkdir -p data/upstream_universe data/upstream_features data/upstream_prices
          gh run download "$U" --name canonical-universe --dir data/upstream_universe
          gh run download "$F" --name market-feature-engine --dir data/upstream_features
          gh run download "$Q" --name underlying-price-layer --dir data/upstream_prices
      - name: Build broad-universe Valuation (full canonical universe, not a pre-selected Top-N)
        run: |
          python -m src.orchestration.build_valuation_scenarios --universe data/upstream_universe/cedear_universe_master.parquet --underlying-prices data/upstream_prices/underlying_prices.parquet --policy config/valuation_policy.yml --etf-sources config/etf_issuer_sources.yml --non-equity-policy config/non_equity_tracker_policy.yml --output-dir data/canonical/valuation_broad
      - name: Build and certify value-first Research Top-N
        run: |
          EXPECTED=$(python -c "import json; print(json.load(open('data/upstream_universe/universe_manifest.json'))['canonical_eligible_count'])")
          python -m src.orchestration.build_value_research_screening --universe data/upstream_universe/cedear_universe_master.parquet --features data/upstream_features/market_features.parquet --valuation data/canonical/valuation_broad/valuation_scenarios.parquet --policy config/value_screening_policy.yml --top-n 30 --expected-count "$EXPECTED" --output-dir data/canonical/research
          python - <<'PY'
          import json, os
          from pathlib import Path
          integrity=json.load(open('data/canonical/research/research_integrity.json'))
          manifest=json.load(open('data/upstream_universe/universe_manifest.json'))
          expected=int(manifest['canonical_eligible_count'])
          assert integrity['status']=='PASS' and float(integrity['coverage_pct'])==100
          assert int(integrity['universe_count'])==expected
          lineage={
              'research_run_id': int(os.environ['GITHUB_RUN_ID']),
              'universe_run_id': int(os.environ['UNIVERSE_RUN_ID']),
              'feature_run_id': int(os.environ['FEATURE_RUN_ID']),
              'canonical_eligible_universe_count': expected,
              'research_screened_count': int(integrity['universe_count']),
              'e2e_ref': os.environ['GITHUB_REF_NAME'],
              'handoff': 'CERTIFIED_UNIVERSE_TO_RESEARCH_EXACT_RUN'
          }
          Path('data/canonical/research/research_lineage.json').write_text(json.dumps(lineage,indent=2))
          print(json.dumps(lineage,indent=2))
          PY
      - uses: actions/upload-artifact@v4
        with:
          name: research-mvp-screening
          path: data/canonical/research/
          if-no-files-found: error
          retention-days: 90
      - uses: actions/upload-artifact@v4
        with:
          name: canonical-broad-valuation-scenarios
          path: data/canonical/valuation_broad/
          if-no-files-found: error
          retention-days: 90
```

---

## valuation_scenarios.yml ("Build Canonical Valuation Scenarios")

Certifies Research's value-first Top-30, slices the pre-computed broad valuation
down to those exact 30 tickers, and runs Deep Scenario Review V2.2 (the sector-aware
Bull/Base/Bear engine) on them. `dispatch_g4=true` auto-chains `g4_cash_hurdle.yml`.

```yaml
name: Build Canonical Valuation Scenarios

# Fase 2: the full-universe Valuation computation itself now happens in
# weekly_screening.yml (uploaded as canonical-broad-valuation-scenarios),
# ahead of Research's Top-N selection. This workflow no longer computes
# Valuation -- it certifies Research's value-first Top-N, slices the
# pre-computed broad valuation down to those exact 30 tickers, and runs
# Deep Scenario Review V2.2 unchanged. g4_cash_hurdle.yml and everything
# downstream is unaffected: canonical-valuation-scenarios keeps the same
# name, shape and e2e_lineage.json fields as before the cutover.

on:
  workflow_dispatch:
    inputs:
      dispatch_g4:
        description: "Dispatch G4 after Valuation (leave false for isolated V2.2 certification)"
        required: false
        default: false
        type: boolean

concurrency:
  group: valuation-scenarios-main
  cancel-in-progress: true
permissions:
  contents: read
  actions: write
jobs:
  build-valuation-scenarios:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
      E2E_RUN_ID: E2E-MANUAL-${{ github.run_id }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Run V2.2 economic regression tests
        run: pytest -q tests/test_deep_scenario_engine.py
      - name: Resolve Research first and its pre-computed broad Valuation
        run: |
          R=$(gh run list --workflow weekly_screening.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$R" && test "$R" != null
          mkdir -p data/upstream_research data/upstream_universe data/upstream_valuation_broad
          gh run download "$R" --name research-mvp-screening --dir data/upstream_research
          gh run download "$R" --name canonical-broad-valuation-scenarios --dir data/upstream_valuation_broad
          test -f data/upstream_research/research_lineage.json
          U=$(python -c "import json; print(json.load(open('data/upstream_research/research_lineage.json'))['universe_run_id'])")
          Q=$(gh run list --workflow underlying_prices.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          L=$(gh run list --workflow cedear_local_market.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          P=$(gh run list --workflow portfolio_state.yml --branch "${GITHUB_REF_NAME}" --status success --limit 1 --json databaseId --jq '.[0].databaseId')
          for X in "$U" "$Q" "$L" "$P"; do test -n "$X" && test "$X" != null; done
          echo "RESEARCH_RUN_ID=$R" >> "$GITHUB_ENV"; echo "UNIVERSE_RUN_ID=$U" >> "$GITHUB_ENV"; echo "LOCAL_RUN_ID=$L" >> "$GITHUB_ENV"; echo "PORTFOLIO_RUN_ID=$P" >> "$GITHUB_ENV"; echo "PRICE_RUN_ID=$Q" >> "$GITHUB_ENV"
          gh run download "$U" --name canonical-universe --dir data/upstream_universe
      - name: Certify Research and slice the pre-computed broad Valuation to the immutable Top-N
        run: |
          python - <<'PY'
          import json,os,pandas as pd
          from pathlib import Path
          integ=json.load(open('data/upstream_research/research_integrity.json'))
          rl=json.load(open('data/upstream_research/research_lineage.json'))
          assert integ['status']=='PASS' and float(integ['coverage_pct'])==100
          assert rl.get('handoff')=='CERTIFIED_UNIVERSE_TO_RESEARCH_EXACT_RUN',rl
          assert int(rl['research_run_id'])==int(os.environ['RESEARCH_RUN_ID']),rl
          assert int(rl['universe_run_id'])==int(os.environ['UNIVERSE_RUN_ID']),rl
          r=pd.read_parquet('data/upstream_research/research_screening.parquet'); u=pd.read_parquet('data/upstream_universe/cedear_universe_master.parquet'); um=json.load(open('data/upstream_universe/universe_manifest.json')); expected=int(um['canonical_eligible_count'])
          assert expected>0 and len(r)==expected and len(u)==expected,(len(r),len(u),expected)
          assert int(rl['canonical_eligible_universe_count'])==expected,rl
          selected=r.loc[r['selected'].fillna(False).astype(bool)].sort_values('rank').copy(); assert len(selected)==30 and selected['top_n_eligibility'].fillna(False).astype(bool).all()
          tickers=selected.cedear_ticker.astype(str).str.upper().tolist(); assert len(set(tickers))==30
          out=u[u.cedear_ticker.astype(str).str.upper().isin(set(tickers))].copy(); assert len(out)==30; out.to_parquet('data/upstream_universe/research_topn_universe.parquet',index=False)
          broad=pd.read_parquet('data/upstream_valuation_broad/valuation_scenarios.parquet'); assert len(broad)==expected,(len(broad),expected)
          outdir=Path('data/canonical/valuation'); outdir.mkdir(parents=True,exist_ok=True)
          sliced=broad[broad.cedear_ticker.astype(str).str.upper().isin(set(tickers))].copy(); assert len(sliced)==30 and sliced.cedear_ticker.astype(str).str.upper().nunique()==30
          sliced.to_parquet(outdir/'valuation_scenarios.parquet',index=False)
          lineage={'e2e_run_id':os.environ['E2E_RUN_ID'],'e2e_ref':os.environ['GITHUB_REF_NAME'],'research_run_id':int(os.environ['RESEARCH_RUN_ID']),'universe_run_id':int(os.environ['UNIVERSE_RUN_ID']),'feature_run_id':int(rl['feature_run_id']),'canonical_eligible_universe_count':expected,'top_n':30,'topn_tickers':tickers,'research_universe_handoff':rl['handoff'],'valuation_run_id':int(os.environ['GITHUB_RUN_ID']),'price_run_id':int(os.environ['PRICE_RUN_ID']),'local_market_run_id':int(os.environ['LOCAL_RUN_ID']),'portfolio_run_id':int(os.environ['PORTFOLIO_RUN_ID']),'valuation_count':30,'triggering_workflow':'workflow_dispatch'}
          Path('data/canonical/valuation/e2e_lineage.json').write_text(json.dumps(lineage,indent=2))
          print(json.dumps(lineage,indent=2))
          PY
      - name: Run mandatory Deep Scenario Review V2.2 on all Top-N
        run: |
          python - <<'PY'
          import json
          from pathlib import Path
          import pandas as pd
          import yaml
          from src.valuation.deep_scenario_engine import validate_scenarios
          outdir=Path('data/canonical/valuation')
          valuation=pd.read_parquet(outdir/'valuation_scenarios.parquet')
          universe=pd.read_parquet('data/upstream_universe/research_topn_universe.parquet')
          key='cedear_ticker'
          missing=[c for c in universe.columns if c!=key and c not in valuation.columns]
          if missing:
              valuation=valuation.merge(universe[[key]+missing],on=key,how='left',validate='one_to_one')
          policy=yaml.safe_load(Path('config/scenario_review_policy.yml').read_text()) or {}
          reviewed,review_manifest=validate_scenarios(valuation,policy)
          assert len(reviewed)==30, {'deep_review_count':len(reviewed)}
          required=['scenario_sector_model','scenario_sector_source','economic_identity_status','scenario_review_status','scenario_review_blockers','scenario_method','identity_adr_ratio_applied','identity_fx_applied','identity_implied_to_market_ratio']
          missing_required=[c for c in required if c not in reviewed.columns]; assert not missing_required, {'missing_audit_columns':missing_required}
          for c in ['scenario_review_status','scenario_method']:
              assert reviewed[c].fillna('').astype(str).str.len().gt(0).all(), {'empty_audit_column':c}
          equity=reviewed['valuation_engine_type'].fillna('').astype(str).str.upper().eq('EQUITY')
          assert reviewed.loc[equity,'scenario_sector_model'].fillna('').astype(str).str.len().gt(0).all() | (~reviewed.loc[equity,'scenario_validated'].fillna(False).astype(bool)).all()
          reviewed.to_parquet(outdir/'deep_scenario_review_v2_1.parquet',index=False); reviewed.to_csv(outdir/'deep_scenario_review_v2_1.csv',index=False)
          def vc(col): return {str(k):int(v) for k,v in reviewed[col].fillna('N/A').astype(str).value_counts().items()}
          blocker_counts={}
          for raw in reviewed['scenario_review_blockers']:
              vals=raw if isinstance(raw,list) else ([] if raw is None or (isinstance(raw,float) and pd.isna(raw)) else [str(raw)])
              for b in vals:
                  b=str(b).strip()
                  if b: blocker_counts[b]=blocker_counts.get(b,0)+1
          audit_cols=[c for c in ['adr_shares_per_depositary_receipt','fundamental_fx_to_market','economic_unit_normalization_verified','eps_unit','target_price_unit','identity_adr_ratio_applied','identity_fx_applied','identity_implied_price','identity_implied_to_market_ratio','identity_target_unit','identity_eps_unit','identity_flags'] if c in reviewed.columns]
          methodology=review_manifest.get('scenario_methodology_version') or policy.get('methodology_version') or 'SCENARIO-UNKNOWN'
          manifest={'layer':'Deep Scenario Review V2.2','methodology_version':methodology,'top_n_count':30,'sector_counts':vc('scenario_sector_model'),'sector_source_counts':vc('scenario_sector_source'),'economic_identity_status_counts':vc('economic_identity_status'),'scenario_review_status_counts':vc('scenario_review_status'),'blocker_counts':dict(sorted(blocker_counts.items())),'normalization_audit_columns':audit_cols,'scenario_validated_count':int(review_manifest['scenario_validated_count']),'scenario_blocked_count':int(review_manifest['scenario_blocked_count']),'g4_eligible_count':int(reviewed['scenario_validated'].fillna(False).astype(bool).sum()),'fail_closed':True}
          assert manifest['methodology_version']=='SCENARIO-2.2',manifest
          (outdir/'deep_scenario_review_v2_1_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)); print(json.dumps(manifest,indent=2,ensure_ascii=False))
          PY
      - name: Certify V2.2 audit artifact contract
        run: |
          python - <<'PY'
          import json,pandas as pd
          df=pd.read_parquet('data/canonical/valuation/deep_scenario_review_v2_1.parquet'); m=json.load(open('data/canonical/valuation/deep_scenario_review_v2_1_manifest.json'))
          assert len(df)==30 and m['top_n_count']==30 and m['fail_closed'] is True
          assert m['methodology_version']=='SCENARIO-2.2',m
          assert sum(m['scenario_review_status_counts'].values())==30 and sum(m['sector_counts'].values())==30
          assert m['scenario_validated_count']+m['scenario_blocked_count']==30
          assert len(m['normalization_audit_columns'])>=5, {'normalization_audit_columns':m['normalization_audit_columns']}
          print('DEEP_SCENARIO_REVIEW_V2_2_AUDIT_CONTRACT=PASS')
          PY
      - uses: actions/upload-artifact@v4
        with:
          name: canonical-valuation-scenarios
          path: data/canonical/valuation/
          if-no-files-found: error
          retention-days: 90
      - name: Dispatch exact G4 on same ref
        if: ${{ inputs.dispatch_g4 == true }}
        run: gh workflow run g4_cash_hurdle.yml --ref "${GITHUB_REF_NAME}" -f valuation_run_id="${GITHUB_RUN_ID}"
```

---

## g4_cash_hurdle.yml ("Build Valuation G4 Cash Hurdle")

The G4 Cash Hurdle gate: "does this clear cash by enough to be worth the risk."
Consumes the certified Deep Scenario Review output, restricts local-market and
portfolio-fit layers to the immutable Top-30, runs G4, triages any `BLOCKED_BY_DATA`
tickers by root-cause bucket, and auto-dispatches `decisional_risk.yml`.

```yaml
name: Build Valuation G4 Cash Hurdle

on:
  workflow_dispatch:
    inputs:
      valuation_run_id:
        description: Exact successful Build Canonical Valuation Scenarios run id
        required: true
        type: string

permissions:
  contents: read
  actions: write

jobs:
  build-g4:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - name: Run G4 and Deep Scenario regression tests
        run: pytest -q tests/test_g4_cash_hurdle.py tests/test_deep_scenario_engine.py tests/test_g4_blocker_triage.py
      - name: Download exact dispatched valuation artifact
        run: |
          VAL_RUN_ID="${{ inputs.valuation_run_id }}"
          META=$(gh run view "$VAL_RUN_ID" --json workflowName,conclusion,databaseId,headBranch)
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["workflowName"])')" = "Build Canonical Valuation Scenarios"
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["conclusion"])')" = "success"
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["headBranch"])')" = "${GITHUB_REF_NAME}"
          echo "VAL_RUN_ID=$VAL_RUN_ID" >> "$GITHUB_ENV"
          mkdir -p data/upstream_valuation
          gh run download "$VAL_RUN_ID" --name canonical-valuation-scenarios --dir data/upstream_valuation
          python - <<'PY'
          import json,pandas as pd
          d=json.load(open('data/upstream_valuation/e2e_lineage.json'));v=pd.read_parquet('data/upstream_valuation/deep_scenario_review_v2_1.parquet');top={str(x).upper() for x in d['topn_tickers']}
          assert d['top_n']==30 and len(top)==30 and d['valuation_count']==30 and len(v)==30
          assert set(v['cedear_ticker'].astype(str).str.upper())==top
          assert v['scenario_validated'].notna().all(), 'scenario_validated missing for some Top-30 tickers'
          validated_count=int(v['scenario_validated'].astype(bool).sum()); assert 0<=validated_count<=30
          assert d.get('local_market_run_id') and d.get('portfolio_run_id')
          PY
      - name: Download lineage-pinned layers
        run: |
          L=$(python -c "import json;print(json.load(open('data/upstream_valuation/e2e_lineage.json'))['local_market_run_id'])")
          P=$(python -c "import json;print(json.load(open('data/upstream_valuation/e2e_lineage.json'))['portfolio_run_id'])")
          echo "LOCAL_RUN_ID=$L" >> "$GITHUB_ENV"; echo "PORTFOLIO_RUN_ID=$P" >> "$GITHUB_ENV"
          mkdir -p data/upstream_local data/upstream_portfolio
          gh run download "$L" --name cedear-local-market-layer --dir data/upstream_local
          gh run download "$P" --name portfolio-state-engine --dir data/upstream_portfolio
      - name: Restrict candidate layers to immutable Research Top-30
        run: |
          python - <<'PY'
          import json,pandas as pd
          d=json.load(open('data/upstream_valuation/e2e_lineage.json'));top=[str(x).upper().strip() for x in d['topn_tickers']];aliases={'BA.C':'BA','BBV':'BBVA','TRVV':'TRV'}
          for path in ['data/upstream_local/cedear_local_market.parquet','data/upstream_portfolio/portfolio_fit_quantitative.parquet']:
            df=pd.read_parquet(path);col='cedear_ticker' if 'cedear_ticker' in df.columns else 'ticker';raw=df[col].astype(str).str.upper().str.strip();sel=[]
            for t in top:
              m=raw[raw.eq(t)].index.tolist() or [i for i,s in raw.items() if aliases.get(s,s)==aliases.get(t,t)]
              assert len(m)==1,(path,t,m);assert m[0] not in sel;sel.append(m[0])
            o=df.loc[sel].copy().reset_index(drop=True);o[col]=top;assert len(o)==30 and o[col].nunique()==30;o.to_parquet(path,index=False)
          PY
      - name: Build G4 Cash Hurdle from certified V2.2 scenarios
        run: |
          python -m src.orchestration.build_g4_cash_hurdle --local-market data/upstream_local/cedear_local_market.parquet --valuation-inputs data/upstream_valuation/deep_scenario_review_v2_1.parquet --certified-scenario-review --portfolio-fit data/upstream_portfolio/portfolio_fit_quantitative.parquet --positions data/upstream_portfolio/portfolio_positions.parquet --policy config/g4_policy.yml --scenario-policy config/scenario_review_policy.yml --output-dir data/canonical/g4 --brokerage-rate 0.006
          python - <<'PY'
          import json
          from pathlib import Path
          d=json.load(open('data/upstream_valuation/e2e_lineage.json'));m=json.load(open('data/canonical/g4/g4_manifest.json'))
          assert m['methodology_version']=='G4-2.1',m
          assert m['scenario_methodology_version']=='SCENARIO-2.2',m
          assert m['scenario_review_count']==30,m
          assert m['scenario_validated_count']+m['scenario_blocked_count']==30,m
          assert m.get('certified_scenario_review_consumed') is True,m
          assert m['ticker_count']==30 and m['evaluated_count']+m['blocked_count']==30,m
          assert m.get('g4_accounting_complete') is True,m
          d.update({'g4_run_id':int('${{ github.run_id }}'),'valuation_run_id':int('${{ env.VAL_RUN_ID }}'),'local_market_run_id':int('${{ env.LOCAL_RUN_ID }}'),'portfolio_run_id':int('${{ env.PORTFOLIO_RUN_ID }}'),'g4_candidate_count':30,'scenario_review_count':30,'scenario_validated_count':int(m['scenario_validated_count']),'scenario_blocked_count':int(m['scenario_blocked_count']),'scenario_methodology_version':m['scenario_methodology_version'],'g4_methodology_version':m['methodology_version'],'handoff':'CERTIFIED_V2_2_SCENARIO_EXACT_RUN_DISPATCH'})
          Path('data/canonical/g4/e2e_lineage.json').write_text(json.dumps(d,indent=2))
          PY
      - name: Triage any BLOCKED_BY_DATA tickers by root-cause bucket
        run: python -m src.orchestration.build_g4_blocker_triage --scenario-review data/canonical/g4/scenario_review.json --policy config/g4_blocker_triage_policy.yml --output-dir data/canonical/g4
      - name: Upload G4 artifacts
        uses: actions/upload-artifact@v4
        with:
          name: valuation-g4-cash-hurdle
          path: data/canonical/g4/
          if-no-files-found: error
      - name: Dispatch decisional Risk with exact G4 run on same ref
        run: gh workflow run decisional_risk.yml --ref "${GITHUB_REF_NAME}" -f g4_run_id=${{ github.run_id }}
```

---

## decisional_risk.yml ("Build Decisional Risk Gate")

Portfolio-level risk gate downstream of G4. Downloads the exact pinned G4 + portfolio
runs, validates lineage, builds the decisional risk assessment, and auto-dispatches
`investment_committee.yml`.

```yaml
name: Build Decisional Risk Gate

on:
  workflow_dispatch:
    inputs:
      g4_run_id:
        description: Exact successful Build Valuation G4 Cash Hurdle run id
        required: true
        type: string

permissions:
  contents: read
  actions: write

jobs:
  decisional-risk:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - name: Run decisional Risk contract tests
        run: pytest -q tests/test_decisional_risk_g4_contract.py
      - name: Download exact certified G4
        run: |
          G4_RUN_ID="${{ inputs.g4_run_id }}"
          META=$(gh run view "$G4_RUN_ID" --json workflowName,conclusion,databaseId,headBranch)
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["workflowName"])')" = "Build Valuation G4 Cash Hurdle"
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["conclusion"])')" = "success"
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["headBranch"])')" = "${GITHUB_REF_NAME}"
          mkdir -p data/upstream_g4
          gh run download "$G4_RUN_ID" --name valuation-g4-cash-hurdle --dir data/upstream_g4
          python - <<'PY'
          import json
          d=json.load(open('data/upstream_g4/e2e_lineage.json')); m=json.load(open('data/upstream_g4/g4_manifest.json'))
          assert d['g4_run_id']==int('${{ inputs.g4_run_id }}'),d
          for k in ('universe_run_id','research_run_id','valuation_run_id','portfolio_run_id','g4_run_id'):
              assert int(d.get(k,0)) > 0, (k,d)
          assert int(d.get('canonical_eligible_universe_count',0)) > 0,d
          assert int(d['valuation_count']) == 30,d
          assert int(d['g4_candidate_count']) == 30,d
          assert d.get('handoff') == 'CERTIFIED_V2_2_SCENARIO_EXACT_RUN_DISPATCH',d
          assert d.get('scenario_methodology_version') == 'SCENARIO-2.2',d
          assert d.get('g4_methodology_version') == 'G4-2.1',d
          assert m.get('scenario_methodology_version') == 'SCENARIO-2.2',m
          assert m.get('methodology_version') == 'G4-2.1',m
          assert int(d.get('scenario_validated_count',0)) + int(d.get('scenario_blocked_count',0)) == 30,d
          ticker_count=int(m.get('ticker_count',0) or 0)
          evaluated=int(m.get('evaluated_count',0) or 0)
          blocked=int(m.get('blocked_count',0) or 0)
          accounted=int(m.get('accounted_count', evaluated + blocked) or 0)
          assert ticker_count == 30,m
          assert evaluated + blocked == ticker_count,m
          assert accounted == ticker_count,m
          assert bool(m.get('g4_accounting_complete', evaluated + blocked == ticker_count)),m
          if blocked:
              assert m.get('ranking_status') == 'COMPLETE_WITH_DATA_GAPS',m
              # A blocked ticker is a per-ticker data gap, excluded from
              # evaluation on its own -- it no longer vetoes deployment into
              # OTHER, cleanly-evaluated G4_PASS candidates (2026-09-12 fix,
              # see PROJECT_STATE.md). Either outcome is fail-closed-correct
              # depending on whether any clean candidates exist.
              assert m.get('deployment_decision') in ('ALLOW_NEW_DEPLOYMENT', 'NO_NEW_DEPLOYMENT_DATA_GAPS'),m
          PY
      - name: Download exact portfolio pinned by G4 lineage
        run: |
          P=$(python -c "import json;print(json.load(open('data/upstream_g4/e2e_lineage.json'))['portfolio_run_id'])")
          mkdir -p data/upstream_portfolio
          gh run download "$P" --name portfolio-state-engine --dir data/upstream_portfolio
      - name: Build decisional Risk
        run: python -m src.orchestration.build_decisional_risk --g4-dir data/upstream_g4 --portfolio-dir data/upstream_portfolio --risk-run-id ${{ github.run_id }} --output-dir data/canonical/decisional_risk
      - name: Upload decisional Risk artifact
        uses: actions/upload-artifact@v4
        with:
          name: decisional-risk-gate
          path: |
            data/canonical/decisional_risk/decisional_risk.json
            data/canonical/decisional_risk/e2e_lineage.json
          if-no-files-found: error
      - name: Dispatch Committee with exact Risk run on same ref
        run: gh workflow run investment_committee.yml --ref "${GITHUB_REF_NAME}" -f risk_run_id=${{ github.run_id }} -f g4_run_id=${{ inputs.g4_run_id }}
```

---

## investment_committee.yml ("Build Investment Committee Decision")

Final stage. Downloads the exact pinned Risk + G4 runs, the portfolio-state and
broad-valuation artifacts (for existing-holdings stress), builds the Committee
decision (allocator ranks G4_PASS by `risk_adjusted_er`, risk-budget fill), and
certifies the entire end-to-end lineage with a long list of hard assertions before
persisting the Shadow Book.

```yaml
name: Build Investment Committee Decision

on:
  workflow_dispatch:
    inputs:
      risk_run_id:
        required: true
        type: string
      g4_run_id:
        required: true
        type: string

permissions:
  contents: read
  actions: read

jobs:
  committee:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - name: Download exact Risk and G4 artifacts
        run: |
          R="${{ inputs.risk_run_id }}"; G="${{ inputs.g4_run_id }}"
          RM=$(gh run view "$R" --json workflowName,conclusion); GM=$(gh run view "$G" --json workflowName,conclusion)
          test "$(echo "$RM"|python -c 'import json,sys;print(json.load(sys.stdin)["workflowName"])')" = "Build Decisional Risk Gate"
          test "$(echo "$RM"|python -c 'import json,sys;print(json.load(sys.stdin)["conclusion"])')" = "success"
          test "$(echo "$GM"|python -c 'import json,sys;print(json.load(sys.stdin)["workflowName"])')" = "Build Valuation G4 Cash Hurdle"
          test "$(echo "$GM"|python -c 'import json,sys;print(json.load(sys.stdin)["conclusion"])')" = "success"
          mkdir -p data/upstream_risk data/upstream_g4
          gh run download "$R" --name decisional-risk-gate --dir data/upstream_risk
          gh run download "$G" --name valuation-g4-cash-hurdle --dir data/upstream_g4
          python - <<'PY'
          import json
          r=json.load(open('data/upstream_risk/e2e_lineage.json')); g=json.load(open('data/upstream_g4/e2e_lineage.json'))
          assert r['decisional_risk_run_id']==int('${{ inputs.risk_run_id }}'),r
          assert r['g4_run_id']==int('${{ inputs.g4_run_id }}')==g['g4_run_id'],(r,g)
          for k in ('e2e_run_id','universe_run_id','research_run_id','valuation_run_id','local_market_run_id','portfolio_run_id','g4_run_id'):
              assert r.get(k)==g.get(k),(k,r,g)
          assert g.get('scenario_methodology_version')=='SCENARIO-2.2',g
          assert g.get('g4_methodology_version')=='G4-2.1',g
          assert g.get('handoff')=='CERTIFIED_V2_2_SCENARIO_EXACT_RUN_DISPATCH',g
          PY
      - name: Download exact Portfolio State artifact for goal tracking
        run: |
          PORTFOLIO_RUN_ID=$(python -c "import json;print(json.load(open('data/upstream_g4/e2e_lineage.json'))['portfolio_run_id'])")
          mkdir -p data/upstream_portfolio_state
          gh run download "$PORTFOLIO_RUN_ID" --name portfolio-state-engine --dir data/upstream_portfolio_state
      - name: Download exact broad-universe valuation for existing-holdings stress
        run: |
          RESEARCH_RUN_ID=$(python -c "import json;print(json.load(open('data/upstream_g4/e2e_lineage.json'))['research_run_id'])")
          UNIVERSE_RUN_ID=$(python -c "import json;print(json.load(open('data/upstream_g4/e2e_lineage.json'))['universe_run_id'])")
          mkdir -p data/upstream_broad_valuation data/upstream_universe
          gh run download "$RESEARCH_RUN_ID" --name canonical-broad-valuation-scenarios --dir data/upstream_broad_valuation
          gh run download "$UNIVERSE_RUN_ID" --name canonical-universe --dir data/upstream_universe
      - name: Build Committee decision and persist Shadow Book
        run: python -m src.orchestration.build_investment_committee --g4-dir data/upstream_g4 --risk-dir data/upstream_risk --committee-run-id ${{ github.run_id }} --output-dir data/canonical/committee --portfolio-state-manifest data/upstream_portfolio_state/portfolio_state_manifest.json --financial-goal config/financial_goal.yml --positions data/upstream_portfolio_state/portfolio_positions.parquet --broad-valuation data/upstream_broad_valuation/valuation_scenarios.parquet --scenario-policy config/scenario_review_policy.yml --universe data/upstream_universe/cedear_universe_master.parquet
      - name: Final E2E certification contract
        run: |
          python - <<'PY'
          import json
          c=json.load(open('data/canonical/committee/committee_decision.json'))
          l=json.load(open('data/canonical/committee/e2e_lineage.json'))
          s=json.load(open('data/canonical/committee/shadow_book.json'))
          g=json.load(open('data/upstream_g4/g4_manifest.json'))
          r=json.load(open('data/upstream_risk/decisional_risk.json'))
          gl=json.load(open('data/upstream_g4/e2e_lineage.json'))
          eligible=int(l.get('canonical_eligible_universe_count',0) or 0)
          assert eligible > 0,l
          assert eligible == int(gl.get('canonical_eligible_universe_count',0) or 0),(l,gl)
          assert int(l.get('top_n',0) or 0)==30,l
          assert len(l.get('topn_tickers',[]))==30,l
          for k in ('universe_run_id','research_run_id','valuation_run_id','local_market_run_id','portfolio_run_id','g4_run_id','decisional_risk_run_id','committee_run_id'):
              assert int(l.get(k,0)) > 0,(k,l)
          assert l['g4_run_id']==int('${{ inputs.g4_run_id }}'),l
          assert l['decisional_risk_run_id']==int('${{ inputs.risk_run_id }}'),l
          assert l['committee_run_id']==int('${{ github.run_id }}'),l
          assert l['decision_persisted'] is True,l
          scenario_review_count=int(l.get('scenario_review_count',0) or 0)
          scenario_validated_count=int(l.get('scenario_validated_count',0) or 0)
          scenario_blocked_count=int(l.get('scenario_blocked_count',0) or 0)
          assert scenario_review_count==30,l
          assert scenario_validated_count + scenario_blocked_count == scenario_review_count,l
          assert l.get('scenario_methodology_version') == 'SCENARIO-2.2',l
          assert l.get('g4_methodology_version') == 'G4-2.1',l
          assert l.get('handoff') == 'CERTIFIED_V2_2_SCENARIO_EXACT_RUN_DISPATCH',l
          assert g.get('methodology_version') == 'G4-2.1',g
          assert g.get('scenario_methodology_version') == 'SCENARIO-2.2',g
          ticker_count=int(g.get('ticker_count',0) or 0)
          evaluated=int(g.get('evaluated_count',0) or 0)
          blocked=int(g.get('blocked_count',0) or 0)
          passes=int(g.get('pass_count',0) or 0)
          fails=int(g.get('fail_count',0) or 0)
          accounted=int(g.get('accounted_count', evaluated + blocked) or 0)
          assert ticker_count==30,g
          assert evaluated + blocked == ticker_count,g
          assert accounted == ticker_count,g
          assert bool(g.get('g4_accounting_complete', evaluated + blocked == ticker_count)),g
          assert g.get('ranking_status') in {'COMPLETE_ACTIONABLE','COMPLETE_WITH_REVIEW_FLAGS','COMPLETE_WITH_DATA_GAPS'},g
          if blocked:
              # A blocked ticker is a per-ticker data gap (e.g. missing a
              # verified ADR ratio), excluded from G4 evaluation on its own.
              # It no longer vetoes the WHOLE committee decision when other,
              # cleanly-evaluated candidates pass G4 and Risk elsewhere --
              # reviewed and fixed 2026-09-12 (see PROJECT_STATE.md); the old
              # behavior double-counted an isolated gap as risk against
              # unrelated tickers. The gap stays visible either way via
              # ranking_status and secondary_considerations.
              assert g.get('ranking_status') == 'COMPLETE_WITH_DATA_GAPS',g
              assert 'SCENARIO_DATA_GAPS_FAIL_CLOSED' in c.get('secondary_considerations',[]),c
              if g.get('deployment_decision') == 'NO_NEW_DEPLOYMENT_DATA_GAPS':
                  assert c['decision'] == 'HOLD_CASH_NO_ACTION',c
                  if passes==0 and evaluated>0 and fails==evaluated:
                      assert c.get('rationale') == 'NO_CANDIDATE_BEATS_CASH_HURDLE',c
                  else:
                      assert c.get('rationale') in ('NO_TRADE_READY_CANDIDATE','CASH_OPTIMAL_BY_MODEL'),c
              else:
                  assert g.get('deployment_decision') == 'ALLOW_NEW_DEPLOYMENT',g
                  assert c['decision'] in ('CANDIDATES_REQUIRE_EXECUTION_GATE','HOLD_CASH_NO_ACTION'),c
                  if c['decision'] == 'CANDIDATES_REQUIRE_EXECUTION_GATE':
                      assert c.get('rationale') == 'G4_PASS_RISK_PASS',c
          assert r['risk_status']=='PASS',r
          assert r['risk_veto']=='NO',r
          assert c['fabricated_trade_count']==0,c
          ehs=c.get('existing_holdings_stress_metrics'); assert ehs is not None,c
          assert ehs['existing_holdings_assessed_weight'] >= 0,ehs
          assert ehs['existing_holdings_unassessed_weight'] >= 0,ehs
          if c['decision']=='CANDIDATES_REQUIRE_EXECUTION_GATE':
              assert c['allocation_metrics']['existing_holdings_stress_contribution_nav'] >= 0,c
          assert s['e2e_run_id']==l['e2e_run_id'],(s,l)
          assert s['committee_run_id']==l['committee_run_id'],(s,l)
          assert s['order_count']==len(s.get('orders',[])),s
          if c['decision']=='HOLD_CASH_NO_ACTION':
              assert s['order_count']==0,s
          elif c['decision']=='CANDIDATES_REQUIRE_EXECUTION_GATE':
              assert c['g4_pass_count']>0,c
              assert len(c.get('new_trades',[]))>0,c
              assert s['order_count']==len(c['new_trades'])>0,s
              assert c.get('allocation_metrics') is not None,c
              assert c['allocation_metrics']['allocated_count']==len(c['new_trades']),c
          else:
              raise AssertionError(('UNKNOWN_COMMITTEE_DECISION',c))
          gt=c.get('goal_tracking'); assert gt is not None,c
          assert gt.get('goal_status') in {'COMPUTABLE','GOAL_ALREADY_MET','HORIZON_ELAPSED'},gt
          assert gt.get('goal_pace_status') in {'NO_NEW_DEPLOYMENT_THIS_CYCLE','REQUIRED_RETURN_NOT_COMPUTABLE','NEW_DEPLOYMENT_MEETS_OR_EXCEEDS_PACE','NEW_DEPLOYMENT_BELOW_PACE'},gt
          if c['decision']=='HOLD_CASH_NO_ACTION':
              assert gt['goal_pace_status']=='NO_NEW_DEPLOYMENT_THIS_CYCLE',gt
          print(json.dumps({'FINAL_E2E':'PASS','decision':c['decision'],'rationale':c['rationale'],'canonical_eligible_universe_count':eligible,'scenario_validated_count':scenario_validated_count,'scenario_blocked_count':scenario_blocked_count,'scenario_methodology_version':l['scenario_methodology_version'],'g4_methodology_version':l['g4_methodology_version'],'lineage':l},indent=2))
          PY
      - name: Upload Committee and final lineage artifacts
        uses: actions/upload-artifact@v4
        with:
          name: investment-committee-decision
          path: |
            data/canonical/committee/committee_decision.json
            data/canonical/committee/shadow_book.json
            data/canonical/committee/e2e_lineage.json
          if-no-files-found: error
```

---

## e2e_autonomous_certification.yml ("Certify Autonomous CEDEAR E2E")

Meta-workflow: dispatches the entire chain above (universe through committee) on a
single ref in strict dependency order, waits for each stage, certifies every run
shares the same ref (no cross-branch lineage mixing), then downloads and certifies
the final Committee artifact end to end.

```yaml
name: Certify Autonomous CEDEAR E2E

on:
  workflow_dispatch:

permissions:
  contents: read
  actions: write

concurrency:
  group: cedear-certified-e2e
  cancel-in-progress: false

jobs:
  launch:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    env:
      GH_TOKEN: ${{ github.token }}
      E2E_REF: ${{ github.ref_name }}
    steps:
      - uses: actions/checkout@v4
      - name: Create immutable E2E identity
        run: |
          echo "E2E_CERT_ROOT=${GITHUB_RUN_ID}"
          echo "E2E_REF=${E2E_REF}"
      - name: Run deterministic serialized upstream chain
        run: |
          set -euo pipefail
          dispatch_wait () {
            WF="$1"; OUT="$2"; shift 2; BEFORE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            gh workflow run "$WF" --ref "$E2E_REF" "$@"; ID=""
            for i in $(seq 1 30); do
              ID=$(gh run list --workflow "$WF" --event workflow_dispatch --branch "$E2E_REF" --limit 20 --json databaseId,createdAt --jq '[.[] | select(.createdAt >= "'"$BEFORE"'")][0].databaseId // empty')
              [ -n "$ID" ] && break; sleep 2
            done
            test -n "$ID"; echo "$ID" > "$OUT"; echo "$WF [$E2E_REF] -> $ID"; gh run watch "$ID" --exit-status
          }
          dispatch_wait build_universe.yml universe_run_id.txt
          dispatch_wait underlying_prices.yml price_run_id.txt
          dispatch_wait underlying_history.yml history_run_id.txt
          dispatch_wait market_features.yml market_features_run_id.txt
          dispatch_wait risk_correlations.yml correlation_risk_run_id.txt
          dispatch_wait portfolio_state.yml portfolio_run_id.txt
          dispatch_wait cedear_local_market.yml local_market_run_id.txt
          dispatch_wait weekly_screening.yml research_run_id.txt
          dispatch_wait valuation_scenarios.yml valuation_run_id.txt -f dispatch_g4=true
      - name: Wait for exact G4 -> Risk -> Committee handoffs
        run: |
          set -euo pipefail
          V=$(cat valuation_run_id.txt); AFTER=$(gh run view "$V" --json createdAt --jq .createdAt)
          wait_child () {
            WF="$1"; AFTER="$2"; OUT="$3"; ID=""
            for i in $(seq 1 90); do
              ID=$(gh run list --workflow "$WF" --event workflow_dispatch --branch "$E2E_REF" --limit 20 --json databaseId,createdAt,status --jq '[.[] | select(.createdAt >= "'"$AFTER"'")][0].databaseId // empty')
              if [ -n "$ID" ]; then gh run watch "$ID" --exit-status; echo "$ID" > "$OUT"; return 0; fi
              sleep 5
            done
            return 1
          }
          wait_child g4_cash_hurdle.yml "$AFTER" g4_run_id.txt
          G=$(cat g4_run_id.txt); GA=$(gh run view "$G" --json createdAt --jq .createdAt); wait_child decisional_risk.yml "$GA" risk_run_id.txt
          D=$(cat risk_run_id.txt); DA=$(gh run view "$D" --json createdAt --jq .createdAt); wait_child investment_committee.yml "$DA" committee_run_id.txt
      - name: Certify every workflow executed on the V2.1 ref
        run: |
          set -euo pipefail
          for F in universe_run_id.txt price_run_id.txt history_run_id.txt market_features_run_id.txt correlation_risk_run_id.txt portfolio_run_id.txt local_market_run_id.txt research_run_id.txt valuation_run_id.txt g4_run_id.txt risk_run_id.txt committee_run_id.txt; do
            ID=$(cat "$F"); BRANCH=$(gh run view "$ID" --json headBranch --jq .headBranch)
            test "$BRANCH" = "$E2E_REF" || { echo "REF_MISMATCH $F run=$ID branch=$BRANCH expected=$E2E_REF"; exit 1; }
          done
          echo "SAME_REF_CHAIN=PASS ref=$E2E_REF"
      - name: Download final Committee artifact and certify full lineage
        run: |
          U=$(cat universe_run_id.txt); R=$(cat research_run_id.txt); V=$(cat valuation_run_id.txt); G=$(cat g4_run_id.txt); D=$(cat risk_run_id.txt); C=$(cat committee_run_id.txt)
          mkdir -p final; gh run download "$C" --name investment-committee-decision --dir final
          python - "$U" "$R" "$V" "$G" "$D" "$C" "$E2E_REF" <<'PY'
          import json,sys
          u,r,v,g,d,c=map(int,sys.argv[1:7]); ref=sys.argv[7]; l=json.load(open('final/e2e_lineage.json')); dec=json.load(open('final/committee_decision.json')); shadow=json.load(open('final/shadow_book.json'))
          assert l['universe_run_id']==u,(l,u); assert l['research_run_id']==r,(l,r); assert l['valuation_run_id']==v,(l,v); assert l['g4_run_id']==g,(l,g); assert l['decisional_risk_run_id']==d,(l,d); assert l['committee_run_id']==c,(l,c); assert l.get('e2e_ref')==ref,(l,ref)
          n=int(l['canonical_eligible_universe_count']); assert 0<n<304,("V2.1 geography-filtered denominator expected below prior 304",l)
          assert l['decisional_risk_status']=='PASS',l; assert l['decision_persisted'] is True,l; assert dec['fabricated_trade_count']==0,dec; assert shadow['status'] in ('NO_ACTION_PERSISTED','PENDING_EXECUTION_GATE'),shadow
          gt=dec.get('goal_tracking'); assert gt is not None,dec; assert gt.get('goal_status') in ('COMPUTABLE','GOAL_ALREADY_MET','HORIZON_ELAPSED'),gt
          print(json.dumps({'AUTONOMOUS_E2E_V2_1':'PASS','same_ref':ref,'geography_filtered_eligible_count':n,'lineage':l,'decision':dec['decision'],'goal_status':gt.get('goal_status')},indent=2))
          PY
      - name: Persist autonomous certification evidence
        uses: actions/upload-artifact@v4
        with:
          name: autonomous-e2e-certification
          path: |
            *_run_id.txt
            final/e2e_lineage.json
            final/committee_decision.json
            final/shadow_book.json
          if-no-files-found: error
          retention-days: 90
```

---

## g4_v22_shadow_audit_launcher.yml ("G4 V2.2 Shadow Stress Budget Audit")

Audit-only launcher for an experimental G4-2.2 methodology living on a separate,
never-merged branch (`audit/scenario-v2-3-probabilistic-bear`). Checks out that ref,
downloads a certified real G4-2.1 run, and builds a shadow comparison. Explicitly
`shadow_only`, never has production decision authority, never touches Risk/Committee.

```yaml
name: G4 V2.2 Shadow Stress Budget Audit

on:
  workflow_dispatch:
    inputs:
      g4_v21_run_id:
        description: Exact successful certified G4-2.1 run id
        required: true
        default: "34525193005"
        type: string
      audit_ref:
        description: Branch/ref containing G4-2.2 shadow implementation
        required: true
        default: "audit/scenario-v2-3-probabilistic-bear"
        type: string

permissions:
  contents: read
  actions: read

jobs:
  g4-v22-shadow-audit:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - name: Checkout exact audit implementation
        uses: actions/checkout@v4
        with:
          ref: ${{ inputs.audit_ref }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Regression tests
        run: pytest -q tests/test_g4_v22_shadow.py tests/test_g4_cash_hurdle.py tests/test_deep_scenario_v23.py

      - name: Download exact certified G4-2.1 artifact
        run: |
          R="${{ inputs.g4_v21_run_id }}"
          M=$(gh run view "$R" --json workflowName,conclusion,headBranch,headSha)
          echo "$M"
          test "$(echo "$M" | python -c 'import json,sys; print(json.load(sys.stdin)["workflowName"])')" = "Build Valuation G4 Cash Hurdle"
          test "$(echo "$M" | python -c 'import json,sys; print(json.load(sys.stdin)["conclusion"])')" = "success"
          mkdir -p data/upstream_g4
          gh run download "$R" --name valuation-g4-cash-hurdle --dir data/upstream_g4
          python - <<'PY'
          import json
          m=json.load(open('data/upstream_g4/g4_manifest.json'))
          l=json.load(open('data/upstream_g4/e2e_lineage.json'))
          assert m['methodology_version']=='G4-2.1'
          assert m['scenario_methodology_version']=='SCENARIO-2.3'
          assert m['preservation_gate_scenario']=='STRESS'
          assert l['g4_run_id']==int('${{ inputs.g4_v21_run_id }}')
          print('CERTIFIED_G4_2_1_INPUT=PASS')
          PY

      - name: Build G4-2.2 shadow comparison
        run: |
          mkdir -p data/canonical/g4_v22_shadow
          python - <<'PY'
          import json
          from pathlib import Path
          import pandas as pd
          import yaml
          from src.valuation.g4_v22_shadow import build_g4_v22_shadow

          src=Path('data/upstream_g4')
          preferred=['g4_cash_hurdle.parquet','g4_results.parquet','g4_candidates.parquet']
          p=next((src/x for x in preferred if (src/x).exists()),None)
          if p is None:
              ps=list(src.glob('*.parquet'))
              assert len(ps)==1,('G4_PARQUET_NOT_UNIQUE',ps)
              p=ps[0]
          df=pd.read_parquet(p)
          policy=yaml.safe_load(open('config/g4_policy_v22_shadow.yml'))
          out,metrics=build_g4_v22_shadow(df,policy)
          outdir=Path('data/canonical/g4_v22_shadow')
          out.to_parquet(outdir/'g4_v22_shadow_comparison.parquet',index=False)
          out.to_csv(outdir/'g4_v22_shadow_comparison.csv',index=False)
          metrics['source_g4_v21_run_id']=int('${{ inputs.g4_v21_run_id }}')
          metrics['source_g4_v21_artifact']=p.name
          metrics['audit_ref']='${{ inputs.audit_ref }}'
          (outdir/'g4_v22_shadow_manifest.json').write_text(json.dumps(metrics,indent=2))
          print(json.dumps(metrics,indent=2))
          cols=['cedear_ticker','g4_v21_status','g4_v22_shadow_status','stress_return_net','position_stress_contribution_nav','stress_compatible_max_weight','risk_adjusted_er','net_benefit_vs_cash']
          print(out[cols].to_string(index=False))
          PY

      - name: Certify shadow isolation
        run: |
          python - <<'PY'
          import json
          import pandas as pd
          m=json.load(open('data/canonical/g4_v22_shadow/g4_v22_shadow_manifest.json'))
          df=pd.read_parquet('data/canonical/g4_v22_shadow/g4_v22_shadow_comparison.parquet')
          assert m['methodology_version']=='G4-2.2-SHADOW'
          assert m['shadow_only'] is True
          assert m['production_decision_authority'] is False
          assert m['production_chain_unchanged'] is True
          assert m['scenario_methodology_version']=='SCENARIO-2.3'
          assert m['compare_against']=='G4-2.1'
          assert len(df)==m['ticker_count']
          assert df['g4_v22_shadow_only'].all()
          print('G4_2_2_SHADOW_AUDIT_CONTRACT=PASS')
          PY

      - name: Upload G4-2.2 shadow audit
        uses: actions/upload-artifact@v4
        with:
          name: g4-v22-shadow-audit
          path: data/canonical/g4_v22_shadow/
          if-no-files-found: error
          retention-days: 90

# Launcher only. Deliberately no Risk, Committee, Shadow Book or order dispatch.
```

---

## g4_v22_portfolio_stress_launcher.yml ("G4 V2.2 Portfolio Stress Audit")

Same experimental-audit family as above, extended with correlation-aware portfolio
stress shadow accounting. Also `shadow_only`, no production decision authority.

```yaml
name: G4 V2.2 Portfolio Stress Audit
on:
  workflow_dispatch:
    inputs:
      g4_v21_run_id: {description: Exact certified G4-2.1 run id, required: true, default: "34525193005", type: string}
      audit_ref: {description: G4-2.2 audit branch, required: true, default: "audit/scenario-v2-3-probabilistic-bear", type: string}
permissions: {contents: read, actions: read}
jobs:
  portfolio-stress-audit:
    runs-on: ubuntu-latest
    env: {PYTHONPATH: "${{ github.workspace }}", GH_TOKEN: "${{ github.token }}"}
    steps:
      - uses: actions/checkout@v4
        with: {ref: "${{ inputs.audit_ref }}"}
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - name: Regression tests
        run: pytest -q tests/test_g4_v22_shadow.py tests/test_g4_v22_portfolio_stress.py tests/test_g4_cash_hurdle.py tests/test_deep_scenario_v23.py
      - name: Download exact certified G4-2.1
        run: |
          R="${{ inputs.g4_v21_run_id }}"; test "$(gh run view "$R" --json workflowName --jq .workflowName)" = "Build Valuation G4 Cash Hurdle"; test "$(gh run view "$R" --json conclusion --jq .conclusion)" = success
          mkdir -p data/upstream_g4; gh run download "$R" --name valuation-g4-cash-hurdle --dir data/upstream_g4
      - name: Download latest certified risk correlation engine
        run: |
          R=$(gh run list --workflow risk_correlations.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'); test -n "$R"; mkdir -p data/upstream_risk; gh run download "$R" --name risk-correlation-engine --dir data/upstream_risk; test -f data/upstream_risk/correlation_matrix_long.parquet; echo "RISK_RUN_ID=$R" >> "$GITHUB_ENV"
      - name: Build position and portfolio shadow audits
        run: |
          mkdir -p data/canonical/g4_v22_portfolio
          python - <<'PY'
          import json,yaml
          from pathlib import Path
          import pandas as pd
          from src.valuation.g4_v22_shadow import build_g4_v22_shadow
          from src.valuation.g4_v22_portfolio_stress import build_portfolio_stress_shadow
          src=Path('data/upstream_g4'); p=src/'g4_cash_hurdle.parquet'; assert p.exists()
          policy=yaml.safe_load(open('config/g4_policy_v22_shadow.yml')); base=pd.read_parquet(p); pos,posm=build_g4_v22_shadow(base,policy); corr=pd.read_parquet('data/upstream_risk/correlation_matrix_long.parquet'); out,m=build_portfolio_stress_shadow(pos,corr,policy)
          m['source_g4_v21_run_id']=int('${{ inputs.g4_v21_run_id }}'); m['source_risk_run_id']=int('${{ env.RISK_RUN_ID }}'); m['position_shadow_metrics']=posm
          d=Path('data/canonical/g4_v22_portfolio'); out.to_csv(d/'g4_v22_portfolio_stress.csv',index=False); out.to_parquet(d/'g4_v22_portfolio_stress.parquet',index=False); (d/'g4_v22_portfolio_stress_manifest.json').write_text(json.dumps(m,indent=2)); print(json.dumps(m,indent=2)); print(out[out.shadow_selected_for_portfolio_audit][['cedear_ticker','shadow_portfolio_weight','stress_return_net','shadow_position_stress_contribution_nav','risk_adjusted_er']].to_string(index=False))
          PY
      - name: Certify shadow isolation and portfolio contract
        run: |
          python - <<'PY'
          import json
          m=json.load(open('data/canonical/g4_v22_portfolio/g4_v22_portfolio_stress_manifest.json')); assert m['methodology_version']=='G4-2.2-SHADOW'; assert m['portfolio_stress_methodology']=='PORTFOLIO-STRESS-1.1-ECONOMIC-FIRST'; assert m['shadow_only'] and not m['production_decision_authority'] and m['production_chain_unchanged']; assert m['correlation_aware_stress_is_diagnostic_only']; assert m['portfolio_gross_stress_budget_ok']; print('G4_2_2_PORTFOLIO_STRESS_AUDIT=PASS')
          PY
      - uses: actions/upload-artifact@v4
        with: {name: g4-v22-portfolio-stress-audit, path: data/canonical/g4_v22_portfolio/, if-no-files-found: error, retention-days: 90}
# Audit launcher only: no Risk, Committee, Shadow Book or order dispatch.
```

---

## scenario_v23_sensitivity_audit.yml

Audit-only: rebuilds a certified V2.2 Top-30 baseline under the experimental
Scenario-2.3 methodology (also on `audit/scenario-v2-3-probabilistic-bear`) and
reports sensitivity statistics (expected-return deltas, probabilistic bear vs. the
old mechanical bear). Never writes back to production.

```yaml
name: Scenario V2.3 Sensitivity Audit

on:
  workflow_dispatch:
    inputs:
      valuation_run_id:
        description: Certified V2.2 valuation run used as immutable comparison baseline
        required: true
        default: "34510886689"
        type: string

permissions:
  contents: read
  actions: read

jobs:
  audit-v23:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}
      GH_TOKEN: ${{ github.token }}
      V23_REF: audit/scenario-v2-3-probabilistic-bear
    steps:
      - name: Checkout isolated Scenario V2.3 implementation
        uses: actions/checkout@v4
        with:
          ref: ${{ env.V23_REF }}
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - name: Certify isolated code ref and V2.3 policy
        run: |
          test "$(git branch --show-current)" = "$V23_REF"
          python - <<'PY'
          from pathlib import Path
          import yaml
          p=yaml.safe_load(Path('config/scenario_review_policy.yml').read_text()) or {}
          assert p.get('methodology_version')=='SCENARIO-2.3',p
          print('ISOLATED_SCENARIO_V2_3_REF=PASS')
          PY
      - name: Run V2.2 compatibility and V2.3 distribution regressions
        run: pytest -q tests/test_deep_scenario_engine.py tests/test_deep_scenario_v23.py
      - name: Download immutable certified V2.2 baseline
        run: |
          R="${{ inputs.valuation_run_id }}"
          META=$(gh run view "$R" --json workflowName,conclusion,databaseId)
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["workflowName"])')" = "Build Canonical Valuation Scenarios"
          test "$(echo "$META"|python -c 'import json,sys;print(json.load(sys.stdin)["conclusion"])')" = "success"
          mkdir -p data/baseline
          gh run download "$R" --name canonical-valuation-scenarios --dir data/baseline
          test -f data/baseline/deep_scenario_review_v2_1.parquet
      - name: Rebuild same Top-N under Scenario V2.3 and audit sensitivity
        run: |
          python - <<'PY'
          import json
          from pathlib import Path
          import numpy as np
          import pandas as pd
          import yaml
          from src.valuation.deep_scenario_engine import validate_scenarios
          base=pd.read_parquet('data/baseline/deep_scenario_review_v2_1.parquet')
          assert len(base)==30
          policy=yaml.safe_load(Path('config/scenario_review_policy.yml').read_text()) or {}
          assert policy['methodology_version']=='SCENARIO-2.3'
          v23,manifest=validate_scenarios(base,policy)
          assert len(v23)==30
          valid=v23['scenario_validated'].fillna(False).astype(bool)
          equities=v23['valuation_engine_type'].fillna('').astype(str).str.upper().eq('EQUITY') & valid
          assert (v23.loc[equities,'stress_target_price'] < v23.loc[equities,'bear_target_price']).all()
          assert (v23.loc[equities,'bear_target_price'] < v23.loc[equities,'base_target_price']).all()
          assert (v23.loc[equities,'base_target_price'] < v23.loc[equities,'bull_target_price']).all()
          assert (v23.loc[equities,'stress_probability']==0).all()
          ps=v23.loc[valid,['bull_probability','base_probability','bear_probability']].sum(axis=1)
          assert np.allclose(ps,1.0)
          def expected_return(df):
              cur=pd.to_numeric(df['current_price'],errors='coerce')
              return (pd.to_numeric(df['bull_target_price'],errors='coerce')/cur-1)*pd.to_numeric(df['bull_probability'],errors='coerce') + (pd.to_numeric(df['base_target_price'],errors='coerce')/cur-1)*pd.to_numeric(df['base_probability'],errors='coerce') + (pd.to_numeric(df['bear_target_price'],errors='coerce')/cur-1)*pd.to_numeric(df['bear_probability'],errors='coerce')
          old=base.copy(); old_valid=old['scenario_validated'].fillna(False).astype(bool)
          old_er=expected_return(old); new_er=expected_return(v23)
          comparison=pd.DataFrame({'cedear_ticker':v23['cedear_ticker'],'scenario_validated_v22':old_valid,'scenario_validated_v23':valid,'current_price':v23['current_price'],'v22_bear_target':base['bear_target_price'],'v23_stress_target':v23['stress_target_price'],'v23_probabilistic_bear_target':v23['bear_target_price'],'base_target':v23['base_target_price'],'bull_target':v23['bull_target_price'],'v22_expected_return':old_er,'v23_expected_return':new_er,'expected_return_delta':new_er-old_er,'v23_stress_return':pd.to_numeric(v23['stress_target_price'],errors='coerce')/pd.to_numeric(v23['current_price'],errors='coerce')-1,'v23_bear_return':pd.to_numeric(v23['bear_target_price'],errors='coerce')/pd.to_numeric(v23['current_price'],errors='coerce')-1,'v23_bull_probability':v23['bull_probability'],'v23_base_probability':v23['base_probability'],'v23_bear_probability':v23['bear_probability']})
          eligible=comparison[comparison['scenario_validated_v22'] & comparison['scenario_validated_v23']].copy()
          def stats(s):
              s=pd.to_numeric(s,errors='coerce').dropna(); return {'count':int(len(s)),'mean':float(s.mean()),'median':float(s.median()),'min':float(s.min()),'max':float(s.max())}
          report={'methodology_version':'SCENARIO-2.3','baseline_valuation_run_id':int('${{ inputs.valuation_run_id }}'),'top_n_count':30,'v22_validated_count':int(old_valid.sum()),'v23_validated_count':int(valid.sum()),'same_candidate_sensitivity_count':int(len(eligible)),'v22_expected_return':stats(eligible['v22_expected_return']),'v23_expected_return':stats(eligible['v23_expected_return']),'v23_stress_return':stats(eligible['v23_stress_return']),'v23_probabilistic_bear_return':stats(eligible['v23_bear_return']),'v22_er_above_5pct':int((eligible['v22_expected_return']>.05).sum()),'v23_er_above_5pct':int((eligible['v23_expected_return']>.05).sum()),'v22_er_above_8pct':int((eligible['v22_expected_return']>.08).sum()),'v23_er_above_8pct':int((eligible['v23_expected_return']>.08).sum()),'stress_is_not_probabilized':True,'g4_policy_changed':False,'v23_code_ref':'audit/scenario-v2-3-probabilistic-bear'}
          Path('data/audit').mkdir(parents=True,exist_ok=True)
          comparison.to_csv('data/audit/scenario_v22_vs_v23_28_candidate_sensitivity.csv',index=False)
          v23.to_parquet('data/audit/deep_scenario_review_v2_3.parquet',index=False)
          Path('data/audit/scenario_v23_sensitivity_report.json').write_text(json.dumps(report,indent=2))
          print(json.dumps(report,indent=2))
          PY
      - uses: actions/upload-artifact@v4
        with:
          name: scenario-v23-sensitivity-audit
          path: data/audit/
          if-no-files-found: error
          retention-days: 90
```

---

## Secrets referenced (not reproduced here, never committed)

- `FINNHUB_TOKEN` — used by `build_universe.yml` and `weekly_screening.yml`.
- `IOL_USERNAME` / `IOL_PASSWORD` — used by `cedear_local_market.yml` (IOL
  Inversiones broker connector, `src/connectors/iol.py`).

## Scheduled Routines that used to dispatch this chain (also removed 2026-10-04)

Two scheduled triggers used to drive this chain automatically and were deleted
alongside the workflow files (per Daniel's explicit instruction, same session):

- **"Weekly CEDEAR pipeline check-in"** (was `trig_018h97kx8AcaBsDuSvFfN2NF`,
  fired Fridays ~20:00 UTC): dispatched `weekly_screening.yml` -> `valuation_scenarios.yml`
  (`dispatch_g4=true`, auto-chaining G4 -> Risk -> Committee), then reported
  G4_PASS/Committee decision/goal pace and acted on `g4_blocker_triage.json` per
  bucket (see `config/g4_blocker_triage_policy.yml` and
  `src/orchestration/build_g4_blocker_triage.py`, both still in the codebase,
  untouched by this removal).
- **"Weekly value-first shadow check"** (was `trig_01WDQG2usnUgpnmQpQywBAGD`):
  already stale before this removal — it targeted `value_research_shadow.yml`/
  `value_research_shadow_g4.yml`, retired 2026-09-14. Deleted as housekeeping in
  the same pass.

To restore the automation: recreate the workflow files from this archive, then
recreate a scheduled trigger with the first Routine's prompt text (reconstructable
from `PROJECT_STATE.md`'s session history, which documents exactly what it checked
and how it acted on each triage bucket).
