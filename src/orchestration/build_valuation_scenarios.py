from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.connectors.finnhub import FinnhubConnector
from src.connectors.issuer_holdings import HoldingsSnapshot, IssuerHoldingsConnector, IssuerHoldingsError
from src.connectors.non_equity_tracker import NonEquityTrackerConnector
from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import ConstituentScenario, build_etf_scenario
from src.valuation.etf_issuer_engine import build_issuer_etf_scenario
from src.valuation.non_equity_tracker_engine import build_non_equity_tracker_scenario


def _is_etf(cedear_ticker: str, instrument_type: object, issuer_name: object, policy: dict) -> bool:
    text = f"{instrument_type or ''} {issuer_name or ''}".upper()
    if re.search(r"\bETF\b|\bETP\b|EXCHANGE\s+TRADED\s+FUND", text): return True
    return cedear_ticker.upper() in {str(t).strip().upper() for t in policy.get("instrument_overrides", {}).get("etf_like_tickers", []) if str(t).strip()}


def _price_map(prices: pd.DataFrame) -> dict[str, float]:
    frame = prices.copy(); ticker_col = "cedear_ticker" if "cedear_ticker" in frame.columns else "ticker"
    if ticker_col not in frame.columns: return {}
    price_col = next((c for c in ("last_close", "close", "adjusted_close", "current_price") if c in frame.columns), None)
    if price_col is None: return {}
    frame[price_col] = pd.to_numeric(frame[price_col], errors="coerce")
    return frame.dropna(subset=[price_col]).set_index(ticker_col)[price_col].astype(float).to_dict()


def _load_issuer_sources(path: str) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}; sources = raw.get("sources", {}) or {}; template = str(raw.get("secondary_template") or "").strip(); fallbacks = {str(t).upper() for t in raw.get("secondary_fallback_tickers", [])}
    for ticker, cfg in sources.items():
        if str(ticker).upper() in fallbacks and template and isinstance(cfg, dict) and "secondary" not in cfg:
            cfg["secondary"] = {"provider": "StockAnalysis", "mode": "html_table", "url": template.format(ticker=str(ticker).lower())}
    return sources


def _issuer_source_symbol(cedear: str, underlying: str, sources: dict[str, Any]) -> str:
    """Issuer configuration is keyed by CEDEAR/fund identity, not provider quote alias."""
    for symbol in (cedear.upper(), underlying.upper()):
        if symbol in sources: return symbol
    return cedear.upper()


def _ready_equity(row: dict[str, Any] | None) -> bool: return bool(row and row.get("valuation_status") == "VALUATION_READY")


def _estimate_etf_plan(snapshot: HoldingsSnapshot, equity_scenarios: dict[str, dict], policy: dict) -> dict[str, Any]:
    quality = policy.get("quality", {}) or {}; min_covered=float(quality.get("minimum_etf_covered_weight",.50)); min_valid=int(quality.get("minimum_etf_valid_holdings",5)); default_limit=int(quality.get("maximum_etf_holdings_to_analyze",50)); cap=int(quality.get("maximum_direct_constituent_lookups_per_etf",12)); max_holdings=snapshot.max_holdings_to_analyze or default_limit
    holdings=sorted(snapshot.holdings,key=lambda x:float(x.get("percent") or 0),reverse=True)[:max_holdings]; scale=1.0 if sum(float(h.get("percent") or 0) for h in holdings)<=1.5 else 100.0; cached_weight=0.; cached_count=0; missing=[]
    for h in holdings:
        symbol=str(h.get("symbol") or "").strip().upper(); weight=float(h.get("percent") or 0)/scale
        if not symbol or weight<=0: continue
        if _ready_equity(equity_scenarios.get(symbol)): cached_weight+=weight; cached_count+=1
        else: missing.append(weight)
    needed=0; feasible=cached_weight>=min_covered and cached_count>=min_valid
    if not feasible:
        rw,rc=cached_weight,cached_count
        for weight in missing:
            needed+=1; rw+=weight; rc+=1
            if rw>=min_covered and rc>=min_valid: feasible=needed<=cap; break
        if needed>cap: feasible=False
    return {"cached_weight":cached_weight,"cached_count":cached_count,"uncached_count":len(missing),"estimated_lookups_needed":needed if feasible else cap+1,"estimated_feasible_within_per_fund_cap":feasible,"coverage_gap":max(0.,min_covered-cached_weight)}


def _blocker_diagnostics(result: pd.DataFrame):
    counts=Counter(); tickers=defaultdict(list)
    if result.empty or "blockers" not in result.columns: return {},{}
    for _,row in result.iterrows():
        ticker=str(row.get("cedear_ticker") or row.get("underlying_ticker") or "UNKNOWN"); blockers=row.get("blockers")
        if isinstance(blockers,str):
            try: blockers=json.loads(blockers)
            except json.JSONDecodeError: blockers=[blockers]
        if not isinstance(blockers,list): continue
        for blocker in blockers:
            code=str(blocker).strip()
            if code: counts[code]+=1; tickers[code].append(ticker)
    return dict(sorted(counts.items(),key=lambda x:(-x[1],x[0]))),{k:sorted(set(v)) for k,v in sorted(tickers.items())}


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--universe",required=True); p.add_argument("--underlying-prices",required=True); p.add_argument("--policy",default="config/valuation_policy.yml"); p.add_argument("--etf-sources",default="config/etf_issuer_sources.yml"); p.add_argument("--non-equity-policy",default="config/non_equity_tracker_policy.yml"); p.add_argument("--output-dir",default="data/canonical/valuation"); args=p.parse_args()
    universe=pd.read_parquet(args.universe).sort_values("cedear_ticker"); prices=pd.read_parquet(args.underlying_prices); policy=yaml.safe_load(Path(args.policy).read_text()) or {}; tracker_policy=yaml.safe_load(Path(args.non_equity_policy).read_text()) or {}; source_cfg=_load_issuer_sources(args.etf_sources); finnhub=FinnhubConnector(); issuer_holdings=IssuerHoldingsConnector(source_cfg); tracker_connector=NonEquityTrackerConnector(tracker_policy); prices_by_cedear=_price_map(prices)
    classified=[(item,_is_etf(str(item.get("cedear_ticker") or "").upper(),item.get("instrument_type"),item.get("issuer_name"),policy)) for _,item in universe.iterrows()]; rows={}; equities={}; cache={}; quality=policy.get("quality",{}) or {}; limit=int(quality.get("maximum_global_direct_constituent_lookups",60)); budget={"initial":limit,"remaining":limit}; premium=bool((policy.get("provider_fallbacks",{}) or {}).get("finnhub_premium_etf_enabled",False)); equity_count=etf_count=issuer_ready=finnhub_ready=non_equity_ready=0
    for item,is_etf in classified:
        if is_etf: continue
        cedear=str(item.get("cedear_ticker") or "").upper(); underlying=str(item.get("underlying_ticker") or cedear).upper(); scenario=build_equity_scenario(underlying,prices_by_cedear.get(cedear),finnhub,policy); scenario.update({"cedear_ticker":cedear,"underlying_ticker":underlying,"instrument_type":item.get("instrument_type"),"valuation_engine_type":"EQUITY","methodology_version":policy.get("methodology_version","VAL-1.0")}); rows[cedear]=scenario; equities[underlying]=scenario; equity_count+=1
    non_equity={str(t).upper() for t in policy.get("instrument_overrides",{}).get("non_equity_trackers",[])}; work=[]
    for item,is_etf in classified:
        if not is_etf: continue
        cedear=str(item.get("cedear_ticker") or "").upper(); underlying=str(item.get("underlying_ticker") or cedear).upper(); source_symbol=_issuer_source_symbol(cedear,underlying,source_cfg)
        if underlying in non_equity: work.append({"item":item,"cedear":cedear,"underlying":underlying,"source_symbol":source_symbol,"snapshot":None,"plan":None,"non_equity":True}); continue
        try: snapshot=issuer_holdings.fetch(source_symbol)
        except IssuerHoldingsError: snapshot=None
        plan=_estimate_etf_plan(snapshot,equities,policy) if snapshot else {"cached_weight":0.,"estimated_lookups_needed":10**6,"estimated_feasible_within_per_fund_cap":False,"coverage_gap":1.}
        work.append({"item":item,"cedear":cedear,"underlying":underlying,"source_symbol":source_symbol,"snapshot":snapshot,"plan":plan,"non_equity":False})
    issuer_work=[w for w in work if not w["non_equity"]]; issuer_work.sort(key=lambda w:(0 if w["plan"].get("estimated_feasible_within_per_fund_cap") else 1,int(w["plan"].get("estimated_lookups_needed",10**6)),float(w["plan"].get("coverage_gap",1.)),w["underlying"])); ordered=[w for w in work if w["non_equity"]]+issuer_work; planner=[]
    for w in ordered:
        item,cedear,underlying=w["item"],w["cedear"],w["underlying"]; price=prices_by_cedear.get(cedear)
        if w["non_equity"]: scenario=build_non_equity_tracker_scenario(underlying,price,tracker_connector,tracker_policy); non_equity_ready+=scenario.get("valuation_status")=="VALUATION_READY"
        else:
            before=budget["remaining"]; scenario=build_issuer_etf_scenario(w["source_symbol"],price,finnhub,issuer_holdings,policy,equity_scenarios=equities,constituent_cache=cache,direct_lookup_budget=budget,holdings_snapshot=w.get("snapshot")); used=before-budget["remaining"]; planner.append({"ticker":underlying,"issuer_source_symbol":w["source_symbol"],"actual_direct_lookups_used":used,"valuation_status":scenario.get("valuation_status")}); issuer_ready+=scenario.get("valuation_status")=="VALUATION_READY"
            if scenario.get("valuation_status")!="VALUATION_READY" and premium:
                fallback=build_etf_scenario(underlying,price,finnhub,policy,constituent_cache=cache,direct_lookup_budget=budget)
                if fallback.get("valuation_status")=="VALUATION_READY": scenario=fallback; finnhub_ready+=1
        scenario.update({"cedear_ticker":cedear,"underlying_ticker":underlying,"instrument_type":item.get("instrument_type"),"valuation_engine_type":"ETF","methodology_version":policy.get("methodology_version","VAL-1.0"),"issuer_source_symbol":w.get("source_symbol")}); rows[cedear]=scenario; etf_count+=1
    result=pd.DataFrame([rows[str(item.get("cedear_ticker") or "").upper()] for item,_ in classified]); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True); blocker_counts,blocker_tickers=_blocker_diagnostics(result); json_df=result.copy()
    for col in ("blockers","holding_error_counts"):
        if col in json_df: json_df[col]=json_df[col].map(lambda x:x if isinstance(x,(list,dict)) else ([] if col=="blockers" else {}))
    json_df.to_json(out/"valuation_scenarios.json",orient="records",indent=2,force_ascii=False); parquet=result.copy()
    for col in ("blockers","holding_error_counts"):
        if col in parquet: parquet[col]=parquet[col].map(lambda x:json.dumps(x,ensure_ascii=False) if isinstance(x,(list,dict)) else x)
    parquet.to_parquet(out/"valuation_scenarios.parquet",index=False); ready=int((result["valuation_status"]=="VALUATION_READY").sum()); blocked=int((result["valuation_status"]=="BLOCKED_BY_DATA").sum()); metrics={"layer":"Canonical Valuation Scenarios","methodology_version":policy.get("methodology_version","VAL-1.0"),"created_at":datetime.now(timezone.utc).isoformat(),"ticker_count":len(result),"equity_count":equity_count,"etf_count":etf_count,"ready_count":ready,"blocked_count":blocked,"issuer_etf_ready_count":int(issuer_ready),"finnhub_premium_etf_ready_count":int(finnhub_ready),"non_equity_tracker_ready_count":int(non_equity_ready),"etf_direct_lookup_budget_initial":budget["initial"],"etf_direct_lookup_budget_remaining":budget["remaining"],"etf_planner_order":planner,"coverage_pct":round(ready/len(result)*100,2) if len(result) else 0,"blocker_counts":blocker_counts,"blocker_tickers":blocker_tickers,"pass_full_valuation":bool(len(result) and ready==len(result)),"note":"VAL-1.8 separates CEDEAR/fund issuer identity from underlying provider quote identity."}; (out/"valuation_scenarios_metrics.json").write_text(json.dumps(metrics,indent=2,ensure_ascii=False)); print(json.dumps(metrics,indent=2,ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
