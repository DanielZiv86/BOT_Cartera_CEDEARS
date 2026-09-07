import pandas as pd
from src.universe.loader import eligible_universe_frame,validate_universe
from src.universe.symbol_map import build_symbol_map
from src.universe.official_sources import OfficialUniverseAudit,reconcile_official_identity

def _sample_payload():
    base={"issuer_name":"x","instrument_type":"Acción","ratio":4.0,"underlying_market":"NYSE","comafi_status":"PRIMARY_ACTIVE","caja_byma_status":"BASELINE_CROSS_VALIDATED","eligible":True,"exclusion_reason":"NONE_APPLICABLE","mandate_exception":False,"first_seen":"2026-09-04","last_verified":"2026-09-04","source_refs":["test"],"source_dates":["2026-09-04"],"universe_version":"test-v1","row_status":"HYDRATED_BASELINE_VALIDATED"}
    a=dict(base,cedear_ticker="BBVA",underlying_ticker="BBVA"); b=dict(base,cedear_ticker="IWDA",underlying_ticker="IWDA",instrument_type="ETF tradicional",underlying_market="EUROCLEAR",mandate_exception=True)
    return {"version":"test-v1","Universe_Count":2,"Eligible_Count":2,"rows":[a,b]}

def test_universe_validation_passes(): assert validate_universe(_sample_payload()).is_valid

def test_iwda_exception_is_enforced():
    p=_sample_payload(); p["rows"][1]["mandate_exception"]=False; r=validate_universe(p); assert not r.is_valid and any("IWDA" in e for e in r.errors)

def test_official_reconciliation_resolves_local_symbol_distinct_from_underlying():
    source=eligible_universe_frame(_sample_payload()).iloc[[0]].copy()
    comafi=pd.DataFrame([{"program_name":"Banco Bilbao","cedear_byma_symbol":"BBV","underlying_symbol":"BBVA"}])
    out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols={"BBV"},verified_at="now"))
    row=out.iloc[0]; assert row["cedear_byma_symbol"]=="BBV"; assert bool(row["byma_tradable"]); assert bool(row["eligible_for_research"])

def test_symbol_map_routes_local_providers_to_byma_symbol():
    frame=pd.DataFrame([{"cedear_ticker":"BBV","legacy_cedear_ticker":"BBVA","cedear_byma_symbol":"BBV","underlying_ticker":"BBVA","underlying_market":"NYSE","instrument_type":"Acción","ratio":4.0,"mandate_exception":False,"byma_tradable":True}])
    aliases={"mapping_version":"2.0","providers":{"yahoo":{},"stooq":{}},"market_suffixes":{"stooq":{"NYSE":".US"}}}
    result=build_symbol_map(frame,aliases,providers=("yahoo","stooq","iol","data912")); row=result.iloc[0]
    assert row["cedear_ticker"]=="BBV" and row["canonical_underlying"]=="BBVA"; assert row["iol_symbol"]=="BBV" and row["data912_symbol"]=="BBV"; assert row["yahoo_symbol"]=="BBVA" and row["stooq_symbol"]=="BBVA.US"

def test_reconciliation_fails_closed_when_not_in_byma():
    source=eligible_universe_frame(_sample_payload()).iloc[[0]].copy(); comafi=pd.DataFrame([{"program_name":"Banco Bilbao","cedear_byma_symbol":"BBV","underlying_symbol":"BBVA"}])
    out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols=set(),verified_at="now")); assert not bool(out.iloc[0]["eligible_for_research"])
