from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
import yaml
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

def apply_universe_inclusions(canonical: pd.DataFrame, inc: dict, exclusion_set: set[str]):
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
        else:
            out=pd.concat([out,pd.DataFrame([overlay])],ignore_index=True); included.append(ticker)
    return out,included,overlaid

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--aliases",default="config/symbol_aliases.yml"); p.add_argument("--exclusions",default="config/mandate_exclusions.yml"); p.add_argument("--inclusions",default="config/universe_inclusions.yml"); p.add_argument("--output-dir",default="data/canonical"); args=p.parse_args()
    payload=load_universe_json(args.input); validation=validate_universe(payload)
    if not validation.is_valid or validation.errors: raise SystemExit("Universe validation failed:\n- "+"\n- ".join(validation.errors))
    source=eligible_universe_frame(payload); exc=load_mandate_exclusions(args.exclusions); inc=load_universe_inclusions(args.inclusions); exclusion_set=set(exc.get("tickers",[]))
    source_tickers=set(source["cedear_ticker"].astype(str).str.upper()); unknown=sorted(exclusion_set-source_tickers)
    if unknown: raise SystemExit("Mandate exclusions contain unknown tickers: "+", ".join(unknown))
    canonical=source.copy(); canonical["user_mandate_excluded"]=canonical["cedear_ticker"].astype(str).str.upper().isin(exclusion_set); canonical["user_mandate_exclusion_reason"]=canonical["user_mandate_excluded"].map(lambda v:exc.get("reason_code","USER_EXCLUDED_FROM_ANALYSIS") if v else None); canonical["universe_override_inclusion"]=False; canonical["universe_override_reason"]=None
    canonical,included,overlaid=apply_universe_inclusions(canonical,inc,exclusion_set)

    audit=fetch_official_universe_audit(); canonical=reconcile_official_identity(canonical,audit)
    active=canonical[~canonical["user_mandate_excluded"]].copy()
    unresolved=active[active["byma_tradability_status"].eq("BYMA_UNRESOLVED")].copy()
    eligible=active[active["eligible_for_research"]].copy()
    eligible["cedear_ticker"]=eligible["cedear_byma_symbol"].fillna(eligible["legacy_cedear_ticker"]).astype(str).str.upper()
    if eligible["cedear_ticker"].duplicated().any(): raise SystemExit("Official reconciliation produced duplicate BYMA symbols")
    eligible=eligible.sort_values("cedear_ticker").reset_index(drop=True); symbol_map=build_symbol_map(eligible,load_alias_config(args.aliases))
    symbol_map_ok=len(symbol_map)==len(eligible) and not symbol_map["cedear_byma_symbol"].isna().any()
    mandate_exception_tickers=sorted(active.loc[active.get("mandate_exception",False).eq(True),"legacy_cedear_ticker"].astype(str).tolist()) if "mandate_exception" in active.columns else []
    eligible_legacy=set(eligible.get("legacy_cedear_ticker",pd.Series(dtype=str)).astype(str).tolist())
    missing_mandate_exceptions=sorted(set(mandate_exception_tickers)-eligible_legacy)

    # Reconcile the historical screening denominator explicitly. The source baseline can be
    # larger than the active Research universe because explicit user mandate exclusions are
    # intentional, auditable removals. New force-inclusions are reported separately so they do
    # not distort the baseline 316 -> active denominator reconciliation.
    baseline_eligible_count=int(payload.get("Eligible_Count") or len(source))
    baseline_post_mandate_count=baseline_eligible_count-len(exclusion_set)
    eligible_new_override_count=int(eligible.get("legacy_cedear_ticker",pd.Series(dtype=str)).astype(str).str.upper().isin(set(included)).sum())
    canonical_baseline_equivalent_count=int(len(eligible))-eligible_new_override_count
    baseline_reconciliation_delta=canonical_baseline_equivalent_count-baseline_post_mandate_count
    baseline_reconciliation_status="PASS" if baseline_reconciliation_delta==0 else "FAIL"

    # Unresolved baseline rows are diagnostic/quarantine items, not automatically gate blockers.
    # A row absent from the current official catalog must not be allowed to freeze the whole
    # current universe merely because an older baseline labelled it eligible. Mandate exceptions
    # remain explicitly eligible and are separately enforced by missing_mandate_exceptions.
    mandate_mask=unresolved.get("mandate_exception",pd.Series(False,index=unresolved.index)).eq(True)
    blocking_unresolved=unresolved[unresolved["eligible_for_research"].eq(True) & ~mandate_mask].copy()
    gate_ok=symbol_map_ok and blocking_unresolved.empty and not missing_mandate_exceptions and baseline_reconciliation_status=="PASS"

    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    eligible.to_parquet(out/"cedear_universe_master.parquet",index=False); eligible.to_json(out/"cedear_universe_master.json",orient="records",indent=2,force_ascii=False)
    canonical[canonical["user_mandate_excluded"]].to_json(out/"cedear_mandate_exclusions.json",orient="records",indent=2,force_ascii=False); canonical[canonical["universe_override_inclusion"]==True].to_json(out/"cedear_universe_inclusions.json",orient="records",indent=2,force_ascii=False)
    unresolved.to_json(out/"cedear_official_reconciliation_unresolved.json",orient="records",indent=2,force_ascii=False)
    blocking_unresolved.to_json(out/"cedear_official_reconciliation_blocking.json",orient="records",indent=2,force_ascii=False)
    symbol_map.to_parquet(out/"security_symbol_map.parquet",index=False); symbol_map.to_json(out/"security_symbol_map.json",orient="records",indent=2,force_ascii=False)
    manifest={"source_version":payload.get("version"),"declared_universe_count":payload.get("Universe_Count"),"source_declared_eligible_count":payload.get("Eligible_Count"),"baseline_eligible_count":baseline_eligible_count,"baseline_mandate_excluded_count":len(exclusion_set),"baseline_mandate_excluded_tickers":sorted(exclusion_set),"baseline_post_mandate_count":baseline_post_mandate_count,"eligible_new_override_count":eligible_new_override_count,"canonical_baseline_equivalent_count":canonical_baseline_equivalent_count,"baseline_reconciliation_delta":baseline_reconciliation_delta,"baseline_reconciliation_status":baseline_reconciliation_status,"official_sources_verified_at":audit.verified_at,"comafi_official_program_count":int(len(audit.comafi)),"byma_pdf_token_count":int(len(audit.byma_symbols)),"official_reconciliation_unresolved_count":int(len(unresolved)),"official_reconciliation_unresolved_legacy_tickers":sorted(unresolved["legacy_cedear_ticker"].astype(str).tolist()),"official_reconciliation_blocking_count":int(len(blocking_unresolved)),"official_reconciliation_blocking_legacy_tickers":sorted(blocking_unresolved["legacy_cedear_ticker"].astype(str).tolist()),"user_mandate_excluded_count":len(exclusion_set),"universe_override_included_count":len(included),"universe_override_overlaid_count":len(overlaid),"universe_override_overlaid_tickers":sorted(overlaid),"canonical_eligible_count":int(len(eligible)),"symbol_map_count":int(len(symbol_map)),"universe_gate_status":"PASS" if gate_ok else "FAIL","mandate_exceptions_expected":mandate_exception_tickers,"mandate_exceptions_missing":missing_mandate_exceptions,"mandate_exceptions":eligible.loc[eligible["mandate_exception"]==True,"cedear_ticker"].tolist() if "mandate_exception" in eligible.columns else []}
    (out/"universe_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8"); print(json.dumps(manifest,indent=2,ensure_ascii=False))
    if not gate_ok:
        raise SystemExit(f"UNIVERSE_GATE_FAILED: baseline_reconciliation={baseline_reconciliation_status} delta={baseline_reconciliation_delta} blocking_unresolved={len(blocking_unresolved)} missing_mandate_exceptions={missing_mandate_exceptions} symbol_map_ok={symbol_map_ok}")
if __name__=="__main__": main()
