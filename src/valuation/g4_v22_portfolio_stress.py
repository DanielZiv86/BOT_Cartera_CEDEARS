from __future__ import annotations

import math
import numpy as np
import pandas as pd


def _correlation_matrix(tickers: list[str], corr_long: pd.DataFrame, floor: float) -> pd.DataFrame:
    req={"ticker_a","ticker_b","correlation"}
    if not req.issubset(corr_long.columns):
        raise ValueError("correlation input missing columns: "+", ".join(sorted(req-set(corr_long.columns))))
    c=pd.DataFrame(np.eye(len(tickers)),index=tickers,columns=tickers,dtype=float)
    lookup={(str(r.ticker_a),str(r.ticker_b)):r.correlation for r in corr_long.itertuples()}
    for i,a in enumerate(tickers):
        for j,b in enumerate(tickers):
            if i==j: continue
            v=lookup.get((a,b),lookup.get((b,a)))
            if v is None or pd.isna(v): raise ValueError(f"missing correlation for {a}/{b}")
            c.loc[a,b]=max(float(v),floor)
    a=(c.to_numpy()+c.to_numpy().T)/2
    vals,vecs=np.linalg.eigh(a); a=vecs@np.diag(np.clip(vals,0,None))@vecs.T
    d=np.sqrt(np.clip(np.diag(a),1e-12,None)); a=a/np.outer(d,d); np.fill_diagonal(a,1.0)
    return pd.DataFrame(a,index=tickers,columns=tickers)


def build_portfolio_stress_shadow(g4_shadow: pd.DataFrame, corr_long: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame,dict]:
    """Economic-eligible, stress-aware shadow allocator.

    Allocation order is deliberately strict:
      1. economic eligibility (SHADOW_PASS),
      2. position Stress sizing,
      3. aggregate gross Portfolio Stress budget,
      4. single-name/concentration caps,
      5. correlation diagnostics.
    Cash is the residual. The allocator may invest anywhere from 0% to 100% NAV.
    It never fills the portfolio with economically ineligible securities.
    """
    r=policy["risk"]; budget=float(r["position_stress_budget_nav"]); pbudget=float(r["portfolio_stress_budget_nav"])
    maxinvest=float(r.get("portfolio_max_invested_weight",1.0)); maxpos=int(r["portfolio_max_positions"])
    minw=float(r["portfolio_min_position_weight"]); cap=float(r["portfolio_max_candidate_weight"]); single=float(r["max_single_name_weight"])
    floor=float(r.get("correlation_floor",0.0))
    df=g4_shadow.copy(); df["shadow_portfolio_weight"]=0.0
    economic=df[df.g4_v22_shadow_status.eq("SHADOW_PASS")].copy()
    economic=economic[pd.to_numeric(economic.stress_return_net,errors="coerce").notna()].copy()
    economic["_rank"]=pd.to_numeric(economic.risk_adjusted_er,errors="coerce").fillna(-np.inf)
    economic=economic.sort_values(["_rank","cedear_ticker"],ascending=[False,True])
    remaining_nav=maxinvest; remaining_stress=pbudget; chosen=[]
    for idx,row in economic.iterrows():
        if len(chosen)>=maxpos or remaining_nav<minw-1e-12: break
        loss=abs(float(row.stress_return_net)); max_by_position=(budget/loss if loss>0 else single); max_by_portfolio=(remaining_stress/loss if loss>0 else single)
        w=min(cap,single,max_by_position,max_by_portfolio,remaining_nav)
        if w+1e-12<minw: continue
        df.loc[idx,"shadow_portfolio_weight"]=w; chosen.append(idx); remaining_nav-=w; remaining_stress-=w*loss
    sel=df[df.shadow_portfolio_weight>0].copy(); tickers=sel.cedear_ticker.astype(str).tolist()
    gross=float((sel.shadow_portfolio_weight*sel.stress_return_net.abs()).sum()) if len(sel) else 0.0
    invested=float(sel.shadow_portfolio_weight.sum()) if len(sel) else 0.0
    corr_stress=0.0; avg_corr=0.0
    if len(sel):
        c=_correlation_matrix(tickers,corr_long,floor); z=sel.set_index("cedear_ticker").loc[tickers]
        s=(z.shadow_portfolio_weight*z.stress_return_net.abs()).to_numpy(float)
        corr_stress=float(math.sqrt(max(0.0,s@c.to_numpy()@s)))
        if len(tickers)>1: avg_corr=float((c.to_numpy().sum()-len(tickers))/(len(tickers)*(len(tickers)-1)))
    weights=sel.shadow_portfolio_weight.to_numpy(float); hhi=float(np.sum(weights**2)/(invested**2)) if invested>0 else 0.0
    effective=float(1/hhi) if hhi>0 else 0.0
    df["shadow_position_stress_contribution_nav"]=df.shadow_portfolio_weight*pd.to_numeric(df.stress_return_net,errors="coerce").abs()
    df["shadow_selected_for_portfolio_audit"]=df.shadow_portfolio_weight>0
    df["economic_eligible_for_shadow_portfolio"]=df.g4_v22_shadow_status.eq("SHADOW_PASS")
    sens={}
    for b in policy.get("shadow_audit_contract",{}).get("portfolio_stress_budget_sensitivity_nav",[]): sens[f"{float(b):.4f}"]=bool(gross<=float(b)+1e-12)
    metrics={"methodology_version":"G4-2.2-SHADOW","portfolio_stress_methodology":"PORTFOLIO-STRESS-1.1-ECONOMIC-FIRST","shadow_only":True,"production_decision_authority":False,"economic_eligible_count":int(len(economic)),"selected_positions":int(len(sel)),"max_invested_weight":maxinvest,"actual_invested_weight":invested,"cash_weight":max(0.0,1-invested),"cash_is_endogenous_residual":True,"portfolio_gross_stress_nav":gross,"portfolio_stress_budget_nav":pbudget,"portfolio_gross_stress_budget_ok":gross<=pbudget+1e-12,"correlation_aware_stress_nav":corr_stress,"correlation_aware_stress_is_diagnostic_only":True,"average_nonnegative_pairwise_correlation":avg_corr,"concentration_hhi":hhi,"effective_number_of_positions":effective,"portfolio_stress_budget_sensitivity":sens,"production_chain_unchanged":True}
    return df,metrics
