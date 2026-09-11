from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _load(path: str) -> pd.DataFrame:
    p=Path(path)
    if p.suffix.lower()=='.json': return pd.read_json(p)
    if p.suffix.lower()=='.csv': return pd.read_csv(p)
    if p.suffix.lower()=='.parquet': return pd.read_parquet(p)
    raise ValueError(f'Unsupported input: {p}')


def audit(frame: pd.DataFrame) -> tuple[pd.DataFrame,dict]:
    evaluated=frame[frame['g4_status']!='BLOCKED_BY_DATA'].copy()
    rows=[]
    for bear,hurdle,unc_scale,dynamic in itertools.product(
        (-.15,-.25,-.40,-.55),(.05,.08,.10),(0.,.5,1.),(False,True)
    ):
        risk_adj=(evaluated['expected_return_net'].astype(float)
                  - evaluated['uncertainty_penalty'].fillna(0).astype(float)*unc_scale
                  - evaluated['correlation_penalty'].fillna(0).astype(float)
                  - evaluated['concentration_penalty'].fillna(0).astype(float))
        net=risk_adj-hurdle
        base_margin=evaluated['minimum_margin_over_hurdle'].fillna(.02).astype(float)
        if dynamic:
            dyn=evaluated.get('required_margin_over_cash',base_margin).fillna(base_margin).astype(float)
            margin=np.where(evaluated.get('valuation_engine_type','').astype(str).str.upper().eq('EQUITY'),dyn,base_margin)
        else:
            margin=base_margin
        passed=(evaluated['bear_return_net'].astype(float)>=bear)&(net>=margin)
        tickers=evaluated.loc[passed,'cedear_ticker'].astype(str).tolist()
        rows.append({'bear_limit':bear,'cash_hurdle':hurdle,'uncertainty_scale':unc_scale,'dynamic_equity_margin':dynamic,'pass_count':len(tickers),'pass_tickers':tickers})
    grid=pd.DataFrame(rows)
    max_pass=int(grid['pass_count'].max()) if not grid.empty else 0
    loosest=grid[(grid.bear_limit==-.55)&(grid.cash_hurdle==.05)&(grid.uncertainty_scale==0)&(~grid.dynamic_equity_margin)]
    production=grid[(grid.bear_limit==-.40)&(grid.cash_hurdle==.08)&(grid.uncertainty_scale==1)&(grid.dynamic_equity_margin)]
    summary={
        'methodology_version':'G4-SENSITIVITY-1.0',
        'evaluated_count':int(len(evaluated)),
        'blocked_count':int((frame['g4_status']=='BLOCKED_BY_DATA').sum()),
        'grid_cases':int(len(grid)),
        'production_pass_count':int(production.iloc[0].pass_count),
        'loosest_tested_pass_count':int(loosest.iloc[0].pass_count),
        'maximum_pass_count_across_grid':max_pass,
        'hold_cash_robust_across_grid':bool(max_pass==0),
        'threshold_relaxation_supported_by_audit':False if max_pass==0 else None,
        'interpretation':'No tested relaxation creates a candidate with both acceptable Bear downside and sufficient expected return margin.' if max_pass==0 else 'Some candidates cross the decision frontier; inspect cases before any policy change.'
    }
    return grid,summary


def main()->int:
    p=argparse.ArgumentParser(description='Non-mutating G4 policy sensitivity audit')
    p.add_argument('--g4-results',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args()
    grid,summary=audit(_load(a.g4_results));out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    grid.to_json(out/'g4_sensitivity_grid.json',orient='records',indent=2)
    grid.to_csv(out/'g4_sensitivity_grid.csv',index=False)
    (out/'g4_sensitivity_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
