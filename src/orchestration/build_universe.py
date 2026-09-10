from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
import yaml
from src.connectors.finnhub import FinnhubConnector,FinnhubError
from src.universe.geography import apply_geography_eligibility,load_geography_policy
from src.universe.loader import eligible_universe_frame,load_universe_json,validate_universe
from src.universe.schema import validate_row
from src.universe.symbol_map import build_symbol_map,load_alias_config
from src.universe.official_sources import fetch_official_universe_audit,reconcile_official_identity

def load_mandate_exclusions(path):
    if not path or not Path(path).exists(): return {"tickers":[]}
    payload=yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}; payload["tickers"]=[str(t).strip().upper() for t in payload.get("tickers",[]) if str(t).strip()]; return payload

def load_universe_inclusions(path):
    if not path or not Path(path).exists(): return {"rows":[]}
    payload=yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for idx,row in enumerate(payload.get("rows",[])):
        errors=validate_row(row,idx)
        if errors: raise ValueError("Invalid universe inclusion row: "+"; ".join(errors))
    return payload

def apply_universe_inclusions(canonical,inc,exclusion_set):
    out=canonical.copy(); included=[]; overlaid=[]
    for row in inc.get("rows",[]):
        ticker=str(row["cedear_ticker"]).strip().upper()
        if ticker in exclusion_set: raise SystemExit(f"Ticker {ticker} cannot be both excluded and force-included")
        mask=out["cedear_ticker"].astype(str).str.strip().str.upper().eq(ticker)
        overlay=dict(row,user_mandate_excluded=False,user_mandate_exclusion_reason=None,universe_override_inclusion=True,universe_override_reason=inc.get("reason_code","EXPLICIT_UNIVERSE_INCLUSION"))
        if mask.any():
            if int(mask.sum()) != 1: raise SystemExit(f"Ticker {ticker} appears more than once in baseline")
            idx=out.index[mask][0]
            for key,value in overlay.items(): out.at[idx,key]=value
            overlaid.append(ticker)
        else: out=pd.concat([out,pd.DataFrame([overlay])],ignore_index=True); included.append(ticker)
    return out,included,overlaid

def hydrate_issuer_geography(frame: pd.DataFrame, finnhub: FinnhubConnector) -> pd.DataFrame:
    """Hydrate issuer domicile independently from exchange location.

    Equity domicile comes from Finnhub company-profile evidence. US-listed funds are
    treated as US fund vehicles; IWDA remains the explicit mandate exception.
    Missing equity country is preserved as unknown and will fail closed downstream.
    """
    out=frame.copy(); countries=[]; sources=[]
    for _,row in out.iterrows():
        ticker=str(row.get("underlying_ticker") or "").strip().upper()
        kind=str(row.get("instrument_type") or "").upper()
        market=str(row.get("underlying_market") or "").upper()
        if bool(row.get("mandate_exception",False)):
            countries.append(""); sources.append("MANDATE_EXCEPTION"); continue
        if "ETF" in kind and market in {"NYSE","NASDAQ","AMEX","NYSE ARCA","NYSEAMERICAN","BATS","CBOE"}:
            countries.append("US"); sources.append("US_LISTED_FUND_VEHICLE"); continue
        try:
            profile=finnhub.company_profile(ticker)
            countries.append(str(profile.get("country") or "").strip().upper())
            sources.append("FINNHUB_COMPANY_PROFILE2" if profile else "FINNHUB_PROFILE_EMPTY")
        except FinnhubError as exc:
            countries.append(""); sources.append(f"FINNHUB_PROFILE_ERROR:{type(exc).__name__}")
    out["issuer_country"]=countries; out["issuer_country_source"]=sources
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--aliases",default="config/symbol_aliases.yml"); p.add_argument("--exclusions",default="config/mandate_exclusions.yml"); p.add_argument("--inclusions",default="config/universe_inclusions.yml"); p.add_argument("--geography-policy",default="config/geography_eligibility.yml"); p.add_argument("--output-dir",default="data/canonical"); args=p.parse_args()
    payload=load_universe_json(args.input); validation=validate_universe(payload)
    if not validation.is_valid or validation.errors: raise SystemExit("Universe validation failed:\n- "+"\n- ".join(validation.errors))
    source=eligible_universe_frame(payload); exc=load_mandate_exclusions(args.exclusions); inc=load_universe_inclusions(args.inclusions); exclusion_set=set(exc.get("tickers",[]))
    unknown=sorted(exclusion_set-set(source["cedear_ticker"].astype(str).str.upper()))
    if unknown: raise SystemExit("Mandate exclusions contain unknown tickers: "+", ".join(unknown))
    canonical=source.copy(); canonical["user_mandate_excluded"]=canonical["cedear_ticker"].astype(str).str.upper().isin(exclusion_set); canonical["user_mandate_exclusion_reason"]=canonical["user_mandate_excluded"].map(lambda v:exc.get("reason_code","USER_EXCLUDED_FROM_ANALYSIS") if v else None); canonical["universe_override_inclusion"]=False; canonical["universe_override_reason"]=None
    canonical,included,overlaid=apply_universe_inclusions(canonical,inc,exclusion_set)

    audit=fetch_official_universe_audit(); canonical=reconcile_official_identity(canonical,audit)
    active=canonical[~canonical["user_mandate_excluded"]].copy(); unresolved=active[active["byma_tradability_status"].eq("BYMA_UNRESOLVED")].copy()
    official_eligible=active[active["eligible_for_research"]].copy()
    finnhub=FinnhubConnector()
    if not finnhub.configured: raise SystemExit("GEOGRAPHY_GATE_FAILED: FINNHUB_TOKEN_NOT_CONFIGURED")
    official_eligible=hydrate_issuer_geography(official_eligible,finnhub)
    official_eligible=apply_geography_eligibility(official_eligible,load_geography_policy(args.geography_policy))
    geography_excluded=official_eligible[~official_eligible["geography_eligible"]].copy()
    eligible=official_eligible[official_eligible["eligible_for_research"]].copy()
    eligible["cedear_ticker"]=eligible["cedear_byma_symbol"].fillna(eligible["legacy_cedear_ticker"]).astype(str).str.upper()
    if eligible["cedear_ticker"].duplicated().any(): raise SystemExit("Official reconciliation produced duplicate BYMA symbols")
    eligible=eligible.sort_values("cedear_ticker").reset_index(drop=True); symbol_map=build_symbol_map(eligible,load_alias_config(args.aliases)); symbol_map_ok=len(symbol_map)==len(eligible) and not symbol_map["cedear_byma_symbol"].isna().any()
    mandate_exception_tickers=sorted(active.loc[active.get("mandate_exception",False).eq(True),"legacy_cedear_ticker"].astype(str).tolist()) if "mandate_exception" in active.columns else []
    eligible_legacy=set(eligible.get("legacy_cedear_ticker",pd.Series(dtype=str)).astype(str).tolist()); missing_mandate_exceptions=sorted(set(mandate_exception_tickers)-eligible_legacy)
    mandate_mask=unresolved.get("mandate_exception",pd.Series(False,index=unresolved.index)).eq(True); blocking_unresolved=unresolved[unresolved["eligible_for_research"].eq(True) & ~mandate_mask].copy()
    geography_accounting_ok=len(official_eligible)==len(eligible)+len(geography_excluded)
    gate_ok=symbol_map_ok and blocking_unresolved.empty and not missing_mandate_exceptions and geography_accounting_ok and len(eligible)>0

    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    eligible.to_parquet(out/"cedear_universe_master.parquet",index=False); eligible.to_json(out/"cedear_universe_master.json",orient="records",indent=2,force_ascii=False)
    geography_excluded.to_json(out/"cedear_geography_exclusions.json",orient="records",indent=2,force_ascii=False)
    canonical[canonical["user_mandate_excluded"]].to_json(out/"cedear_mandate_exclusions.json",orient="records",indent=2,force_ascii=False); canonical[canonical["universe_override_inclusion"]==True].to_json(out/"cedear_universe_inclusions.json",orient="records",indent=2,force_ascii=False)
    unresolved.to_json(out/"cedear_official_reconciliation_unresolved.json",orient="records",indent=2,force_ascii=False); blocking_unresolved.to_json(out/"cedear_official_reconciliation_blocking.json",orient="records",indent=2,force_ascii=False)
    symbol_map.to_parquet(out/"security_symbol_map.parquet",index=False); symbol_map.to_json(out/"security_symbol_map.json",orient="records",indent=2,force_ascii=False)
    reason_counts={str(k):int(v) for k,v in geography_excluded["geography_eligibility_reason"].value_counts().items()}
    manifest={"source_version":payload.get("version"),"declared_universe_count":payload.get("Universe_Count"),"source_declared_eligible_count":payload.get("Eligible_Count"),"official_pre_geography_eligible_count":int(len(official_eligible)),"geography_policy_version":"GEOGRAPHY-2.1","geography_excluded_count":int(len(geography_excluded)),"geography_exclusion_reason_counts":reason_counts,"geography_excluded_tickers":sorted(geography_excluded["legacy_cedear_ticker"].astype(str).tolist()),"geography_accounting_status":"PASS" if geography_accounting_ok else "FAIL","official_sources_verified_at":audit.verified_at,"comafi_official_program_count":int(len(audit.comafi)),"official_reconciliation_unresolved_count":int(len(unresolved)),"official_reconciliation_blocking_count":int(len(blocking_unresolved)),"user_mandate_excluded_count":len(exclusion_set),"universe_override_included_count":len(included),"universe_override_overlaid_count":len(overlaid),"canonical_eligible_count":int(len(eligible)),"symbol_map_count":int(len(symbol_map)),"universe_gate_status":"PASS" if gate_ok else "FAIL","mandate_exceptions_expected":mandate_exception_tickers,"mandate_exceptions_missing":missing_mandate_exceptions,"mandate_exceptions":eligible.loc[eligible["mandate_exception"]==True,"cedear_ticker"].tolist() if "mandate_exception" in eligible.columns else [],"finnhub_geography_diagnostics":finnhub.diagnostics()}
    (out/"universe_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8"); print(json.dumps(manifest,indent=2,ensure_ascii=False))
    if not gate_ok: raise SystemExit(f"UNIVERSE_GATE_FAILED: geography_accounting={geography_accounting_ok} blocking_unresolved={len(blocking_unresolved)} missing_mandate_exceptions={missing_mandate_exceptions} symbol_map_ok={symbol_map_ok}")
if __name__=="__main__": main()
