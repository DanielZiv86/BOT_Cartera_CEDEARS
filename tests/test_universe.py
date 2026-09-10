import pandas as pd
from src.universe.loader import eligible_universe_frame,validate_universe
from src.universe.symbol_map import build_symbol_map
from src.universe.geography import apply_geography_eligibility
from src.universe.official_sources import OfficialUniverseAudit,reconcile_official_identity,_rename_identity_columns,_ensure_identity_schema

def _sample_payload():
    base={"issuer_name":"x","instrument_type":"Acción","ratio":4.0,"underlying_market":"NYSE","comafi_status":"PRIMARY_ACTIVE","caja_byma_status":"BASELINE_CROSS_VALIDATED","eligible":True,"exclusion_reason":"NONE_APPLICABLE","mandate_exception":False,"first_seen":"2026-09-04","last_verified":"2026-09-04","source_refs":["test"],"source_dates":["2026-09-04"],"universe_version":"test-v1","row_status":"HYDRATED_BASELINE_VALIDATED"}
    a=dict(base,cedear_ticker="BBVA",underlying_ticker="BBVA"); b=dict(base,cedear_ticker="IWDA",underlying_ticker="IWDA",instrument_type="ETF tradicional",underlying_market="EUROCLEAR",mandate_exception=True)
    return {"version":"test-v1","Universe_Count":2,"Eligible_Count":2,"rows":[a,b]}

def _geo_policy():
    return {"allowed_us_exchanges":["NYSE","NASDAQ"],"allowed_issuer_countries":{"US":"UNITED_STATES","ES":"EUROPE","GB":"EUROPE"},"mandate_exceptions":["IWDA"],"reason_codes":{"eligible":"ISSUER_US_OR_EUROPE_AND_US_TRADED","country_unknown":"ISSUER_COUNTRY_UNVERIFIED","country_outside_mandate":"ISSUER_OUTSIDE_US_EUROPE","exchange_outside_mandate":"UNDERLYING_NOT_US_TRADED","mandate_exception":"EXPLICIT_USER_MANDATE_EXCEPTION"}}

def test_universe_validation_passes(): assert validate_universe(_sample_payload()).is_valid

def test_iwda_exception_is_enforced():
    p=_sample_payload(); p["rows"][1]["mandate_exception"]=False; r=validate_universe(p); assert not r.is_valid and any("IWDA" in e for e in r.errors)

def test_geography_accepts_us_and_european_issuers_trading_in_us():
    frame=pd.DataFrame([{"cedear_ticker":"JPM","issuer_country":"US","underlying_market":"NYSE","eligible_for_research":True},{"cedear_ticker":"SAN","issuer_country":"ES","underlying_market":"NYSE","eligible_for_research":True}]); out=apply_geography_eligibility(frame,_geo_policy()); assert out["geography_eligible"].tolist()==[True,True]

def test_geography_rejects_brazil_even_when_security_trades_in_us():
    frame=pd.DataFrame([{"cedear_ticker":"PBR","issuer_country":"BR","underlying_market":"NYSE","eligible_for_research":True}]); out=apply_geography_eligibility(frame,_geo_policy()); row=out.iloc[0]; assert not bool(row["geography_eligible"]); assert row["geography_eligibility_reason"]=="ISSUER_OUTSIDE_US_EUROPE"; assert not bool(row["eligible_for_research"])

def test_geography_fails_closed_on_unknown_country():
    frame=pd.DataFrame([{"cedear_ticker":"XYZ","issuer_country":"","underlying_market":"NYSE","eligible_for_research":True}]); out=apply_geography_eligibility(frame,_geo_policy()); assert not bool(out.iloc[0]["eligible_for_research"]); assert out.iloc[0]["geography_eligibility_reason"]=="ISSUER_COUNTRY_UNVERIFIED"

def test_geography_preserves_iwda_explicit_exception():
    frame=pd.DataFrame([{"cedear_ticker":"IWDA","issuer_country":"","underlying_market":"EUROCLEAR","eligible_for_research":True,"mandate_exception":True}]); out=apply_geography_eligibility(frame,_geo_policy()); assert bool(out.iloc[0]["eligible_for_research"]); assert out.iloc[0]["geography_eligibility_reason"]=="EXPLICIT_USER_MANDATE_EXCEPTION"

def test_official_reconciliation_resolves_local_symbol_distinct_from_underlying():
    source=eligible_universe_frame(_sample_payload()).iloc[[0]].copy(); comafi=pd.DataFrame([{"program_name":"Banco Bilbao","cedear_byma_symbol":"BBV","underlying_symbol":"BBVA"}]); out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols={"BBV"},verified_at="now")); row=out.iloc[0]; assert row["cedear_byma_symbol"]=="BBV"; assert row["official_match_method"]=="MATCH_BY_UNDERLYING_SYMBOL"; assert bool(row["byma_tradable"]); assert bool(row["eligible_for_research"])

def test_symbol_map_routes_local_providers_to_byma_symbol():
    frame=pd.DataFrame([{"cedear_ticker":"BBV","legacy_cedear_ticker":"BBVA","cedear_byma_symbol":"BBV","underlying_ticker":"BBVA","underlying_market":"NYSE","instrument_type":"Acción","ratio":4.0,"mandate_exception":False,"byma_tradable":True}]); aliases={"mapping_version":"2.0","providers":{"yahoo":{},"stooq":{}},"market_suffixes":{"stooq":{"NYSE":".US"}}}; result=build_symbol_map(frame,aliases,providers=("yahoo","stooq","iol","data912")); row=result.iloc[0]; assert row["cedear_ticker"]=="BBV" and row["canonical_underlying"]=="BBVA"; assert row["iol_symbol"]=="BBV" and row["data912_symbol"]=="BBV"; assert row["yahoo_symbol"]=="BBVA" and row["stooq_symbol"]=="BBVA.US"

def test_reconciliation_fails_closed_when_not_in_structured_official_list():
    source=eligible_universe_frame(_sample_payload()).iloc[[0]].copy(); comafi=pd.DataFrame([{"program_name":"Other","cedear_byma_symbol":"XYZ","underlying_symbol":"XYZ"}]); out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols={"XYZ"},verified_at="now")); assert not bool(out.iloc[0]["eligible_for_research"]); assert out.iloc[0]["byma_tradability_status"]=="BYMA_UNRESOLVED"

def test_mandate_exception_is_preserved_without_false_byma_confirmation():
    source=eligible_universe_frame(_sample_payload()).iloc[[1]].copy(); comafi=pd.DataFrame([{"program_name":"Other","cedear_byma_symbol":"XYZ","underlying_symbol":"XYZ"}]); out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols={"XYZ"},verified_at="now")); row=out.iloc[0]; assert row["cedear_ticker"]=="IWDA"; assert not bool(row["byma_tradable"]); assert row["official_identity_status"]=="MANDATE_EXCEPTION_NOT_BYMA_CONFIRMED"; assert bool(row["eligible_for_research"])

def test_ambiguous_underlying_does_not_guess_local_symbol():
    source=eligible_universe_frame(_sample_payload()).iloc[[0]].copy(); comafi=pd.DataFrame([{"program_name":"A","cedear_byma_symbol":"BBV","underlying_symbol":"BBVA"},{"program_name":"B","cedear_byma_symbol":"BBVX","underlying_symbol":"BBVA"}]); out=reconcile_official_identity(source,OfficialUniverseAudit(comafi=comafi,byma_symbols={"BBV","BBVX"},verified_at="now")); row=out.iloc[0]; assert pd.isna(row["cedear_byma_symbol"]); assert row["official_match_method"]=="AMBIGUOUS_UNDERLYING_SYMBOL"; assert not bool(row["eligible_for_research"])

def test_caja_table_keeps_only_cedear_stable_identifiers():
    table=pd.DataFrame({"Símbolo BYMA":["SPY"],"Código Caja de Valores Cedear":["8549"],"ISIN Cedear":["ARCAVA460131"],"Código Caja de Valores ETF/Acción":["7747"],"ISIN ETF/Acción":["US78462F1030"]}); renamed=_rename_identity_columns(table,"Caja de Valores"); assert not renamed.columns.duplicated().any(); assert renamed.loc[0,"caja_code"]=="8549"; assert renamed.loc[0,"isin_cedear"]=="ARCAVA460131"; assert "Código Caja de Valores ETF/Acción" in renamed.columns; assert "ISIN ETF/Acción" in renamed.columns; normalized=_ensure_identity_schema(renamed); assert normalized.loc[0,"caja_code"]=="8549"; assert normalized.loc[0,"isin_cedear"]=="ARCAVA460131"
