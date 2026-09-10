from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

COMAFI_PROGRAM_CATALOG_URL = "https://www.comafi.com.ar/Programas-CEDEARs-2483.note.aspx"
COMAFI_SHARES_DETAIL_URL = "https://www.comafi.com.ar/CEDEAR-SHARES-2254.note.aspx"
COMAFI_PROGRAMS_URL = "https://www.comafi.com.ar/custodiaglobal/programas.aspx"
CAJA_CEDEARS_URL = "https://cajadevalores.com.ar/Servicios/Cedears"
BYMA_CEDEARS_URL = "https://www.byma.com.ar/productos/productos-financieros/cedears"

@dataclass(frozen=True)
class OfficialUniverseAudit:
    comafi: pd.DataFrame
    byma_symbols: set[str]
    verified_at: str
    byma_evidence_mode: str = "TEST_OR_LEGACY_STRUCTURED_EVIDENCE"

def _norm(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)): return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def _norm_symbol(value: object) -> str:
    return _norm(value).upper().replace(" ", "")

def _http_get(url: str) -> requests.Response:
    response=requests.get(url,timeout=30,headers={"User-Agent":"CEDEAR-MVP/1.0"}); response.raise_for_status(); return response

def _ensure_identity_schema(frame: pd.DataFrame) -> pd.DataFrame:
    out=frame.copy()
    if out.columns.duplicated().any():
        duplicates=sorted(set(str(c) for c in out.columns[out.columns.duplicated(keep=False)]))
        raise RuntimeError(f"OFFICIAL_SCHEMA_ERROR: duplicate normalized columns: {duplicates}")
    defaults={"program_name":"","cedear_byma_symbol":"","underlying_symbol":"","caja_code":"","isin_cedear":"","country_of_origin":"","underlying_market_official":"","industry_sector_official":"","official_issuer":"","official_source_url":"","official_source_kind":""}
    for col,default in defaults.items():
        if col not in out.columns: out[col]=default
    out["cedear_byma_symbol"]=out["cedear_byma_symbol"].map(_norm_symbol)
    out["underlying_symbol"]=out["underlying_symbol"].map(_norm_symbol)
    out["caja_code"]=out["caja_code"].map(_norm)
    out["isin_cedear"]=out["isin_cedear"].map(lambda x:_norm(x).upper())
    for col in ("country_of_origin","underlying_market_official","industry_sector_official"): out[col]=out[col].map(_norm)
    return out

def _rename_identity_columns(table: pd.DataFrame, issuer: str) -> pd.DataFrame:
    rename={}
    for col in table.columns:
        key=_norm(col).lower()
        if issuer == "Caja de Valores":
            if "símbolo byma" in key or "simbolo byma" in key: rename[col]="cedear_byma_symbol"
            elif key == "cedear de etf" or ("programa" in key and "cedear" in key): rename[col]="program_name"
            elif "código caja de valores cedear" in key or "codigo caja de valores cedear" in key: rename[col]="caja_code"
            elif "isin cedear" in key: rename[col]="isin_cedear"
            continue
        is_underlying=("subyacente" in key or "underlying" in key)
        if "símbolo byma" in key or "simbolo byma" in key or ((("identificación" in key or "identificacion" in key) and "mercado" in key) or "id de mercado" in key): rename[col]="cedear_byma_symbol"
        elif "denomin" in key or ("programa" in key and "cedear" in key): rename[col]="program_name"
        elif "ticker" in key and ("origen" in key or "mercado" in key): rename[col]="underlying_symbol"
        elif key in {"país","pais","país de origen","pais de origen"}: rename[col]="country_of_origin"
        elif key in {"mercado de valor subyacente","mercado de origen"}: rename[col]="underlying_market_official"
        elif key in {"industria o sector","industria","sector"}: rename[col]="industry_sector_official"
        elif ("código caja" in key or "codigo caja" in key) and not is_underlying: rename[col]="caja_code"
        elif "isin" in key and "cedear" in key and not is_underlying: rename[col]="isin_cedear"
    return table.rename(columns=rename)

def _parse_identity_tables(url: str, issuer: str, kind: str, min_rows: int=5) -> pd.DataFrame:
    response=_http_get(url)
    try: tables=pd.read_html(io.StringIO(response.text))
    except ValueError as exc: raise RuntimeError(f"OFFICIAL_PARSE_ERROR: no HTML tables at {url}") from exc
    candidates=[]
    for table in tables:
        if len(table)<min_rows: continue
        out=_ensure_identity_schema(_rename_identity_columns(table.copy(),issuer))
        has_identity=out["caja_code"].ne("") | out["isin_cedear"].ne("") | out["cedear_byma_symbol"].str.match(r"^[A-Z][A-Z0-9./-]{0,15}$",na=False)
        out=out[has_identity].copy()
        if len(out)<min_rows: continue
        out.loc[out["program_name"].eq(""),"program_name"]=out["cedear_byma_symbol"]
        out.loc[out["underlying_symbol"].eq(""),"underlying_symbol"]=out["cedear_byma_symbol"]
        out["official_issuer"]=issuer; out["official_source_url"]=url; out["official_source_kind"]=kind
        cols=["program_name","cedear_byma_symbol","underlying_symbol","caja_code","isin_cedear","country_of_origin","underlying_market_official","industry_sector_official","official_issuer","official_source_url","official_source_kind"]
        candidates.append(out[cols])
    if not candidates: raise RuntimeError(f"OFFICIAL_PARSE_ERROR: identity catalogue not found at {url}")
    combined=pd.concat(candidates,ignore_index=True)
    combined["_key"]=combined.apply(lambda r:f"CAJA:{r.caja_code}" if _norm(r.caja_code) else (f"ISIN:{r.isin_cedear}" if _norm(r.isin_cedear) else f"SYM:{_norm_symbol(r.cedear_byma_symbol)}"),axis=1)
    return combined[combined["_key"].ne("SYM:")].drop_duplicates("_key").drop(columns="_key").reset_index(drop=True)

def _parse_full_current_program_catalog(url: str) -> pd.DataFrame: return _parse_identity_tables(url,"Banco Comafi","COMAFI_FULL_CURRENT_PROGRAM_CATALOG")
def _parse_detailed_identity_table(url: str) -> pd.DataFrame: return _parse_identity_tables(url,"Banco Comafi","COMAFI_DETAILED_IDENTITY_TABLE")

def fetch_comafi_programs() -> pd.DataFrame:
    catalog=_parse_full_current_program_catalog(COMAFI_PROGRAM_CATALOG_URL)
    try: detail=_parse_detailed_identity_table(COMAFI_SHARES_DETAIL_URL)
    except Exception: detail=pd.DataFrame(columns=catalog.columns)
    catalog=_ensure_identity_schema(catalog); detail=_ensure_identity_schema(detail)
    detail_by_caja={r.caja_code:r for r in detail.itertuples(index=False) if _norm(r.caja_code)}
    rows=[]
    for row in catalog.itertuples(index=False):
        rec={c:getattr(row,c) for c in catalog.columns}; d=detail_by_caja.get(_norm(rec.get("caja_code")))
        if d is not None:
            if _norm_symbol(d.cedear_byma_symbol): rec["cedear_byma_symbol"]=_norm_symbol(d.cedear_byma_symbol)
            if _norm_symbol(d.underlying_symbol): rec["underlying_symbol"]=_norm_symbol(d.underlying_symbol)
            if not _norm(rec.get("underlying_market_official")) and _norm(d.underlying_market_official): rec["underlying_market_official"]=_norm(d.underlying_market_official)
            rec["official_source_kind"]="COMAFI_FULL_CATALOG_PLUS_DETAIL_BY_CAJA"
        rows.append(rec)
    return _ensure_identity_schema(pd.DataFrame(rows))

def fetch_caja_programs() -> pd.DataFrame: return _parse_identity_tables(CAJA_CEDEARS_URL,"Caja de Valores","CAJA_DE_VALORES_CURRENT_CEDEAR_CATALOG")

def verify_byma_ceadars_product_page(url: str=BYMA_CEDEARS_URL) -> None:
    response=_http_get(url); text=re.sub(r"\s+"," ",response.text).lower()
    if "cedear" not in text or not any(token in text for token in ("negoci","trading","conversion")): raise RuntimeError("BYMA_PRODUCT_PAGE_VALIDATION_ERROR: CEDEAR market evidence not found")

def _coalesce_official_identity_rows(frame: pd.DataFrame) -> pd.DataFrame:
    frame=_ensure_identity_schema(frame).copy()
    frame["_key"]=frame.apply(lambda r:f"CAJA:{r.caja_code}" if _norm(r.caja_code) else (f"ISIN:{r.isin_cedear}" if _norm(r.isin_cedear) else f"SYM:{_norm_symbol(r.cedear_byma_symbol)}"),axis=1)
    rows=[]
    for _,group in frame[frame["_key"].ne("SYM:")].groupby("_key",sort=False):
        rec={}
        for col in ["program_name","cedear_byma_symbol","underlying_symbol","caja_code","isin_cedear","country_of_origin","underlying_market_official","industry_sector_official"]:
            values=[_norm(v) for v in group[col].tolist() if _norm(v)]; rec[col]=values[0] if values else ""
        for col in ["official_issuer","official_source_url","official_source_kind"]:
            values=[]
            for value in group[col].tolist():
                value=_norm(value)
                if value and value not in values: values.append(value)
            rec[col]=" | ".join(values)
        rows.append(rec)
    return _ensure_identity_schema(pd.DataFrame(rows))

def fetch_official_universe_audit() -> OfficialUniverseAudit:
    verify_byma_ceadars_product_page(); comafi=fetch_comafi_programs(); caja=fetch_caja_programs()
    if len(comafi)<300: raise RuntimeError(f"COMAFI_COVERAGE_ERROR: current catalogue unexpectedly small ({len(comafi)})")
    if len(caja)<20: raise RuntimeError(f"CAJA_COVERAGE_ERROR: current catalogue unexpectedly small ({len(caja)})")
    official=_coalesce_official_identity_rows(pd.concat([comafi,caja],ignore_index=True))
    symbols=set(_norm_symbol(s) for s in official["cedear_byma_symbol"] if _norm_symbol(s))
    return OfficialUniverseAudit(comafi=official,byma_symbols=symbols,verified_at=datetime.now(timezone.utc).isoformat(),byma_evidence_mode="BYMA_MARKET_AUTHORITY_PLUS_COMAFI_AND_CAJA_OFFICIAL_CATALOGS")

def reconcile_official_identity(source: pd.DataFrame,audit: OfficialUniverseAudit) -> pd.DataFrame:
    out=source.copy(); official=_ensure_identity_schema(audit.comafi)
    by_local=set(s for s in official["cedear_byma_symbol"] if s); by_underlying={}; ambiguous=set()
    for underlying,group in official[official["underlying_symbol"].ne("")].groupby("underlying_symbol"):
        syms=sorted(set(s for s in group["cedear_byma_symbol"] if s))
        if len(syms)==1: by_underlying[str(underlying)]=syms[0]
        elif len(syms)>1: ambiguous.add(str(underlying))
    def unique_map(column):
        result={}
        for key,group in official[official[column].astype(str).str.len()>0].groupby(column):
            syms=sorted(set(s for s in group["cedear_byma_symbol"] if s))
            if len(syms)==1: result[_norm(key).upper()]=syms[0]
        return result
    by_caja=unique_map("caja_code"); by_isin=unique_map("isin_cedear")
    official_cajas=set(_norm(v).upper() for v in official["caja_code"] if _norm(v)); official_isins=set(_norm(v).upper() for v in official["isin_cedear"] if _norm(v))
    def resolve(row):
        local=_norm_symbol(row.get("cedear_ticker")); underlying=_norm_symbol(row.get("underlying_ticker")); caja=_norm(row.get("caja_code")).upper(); isin=_norm(row.get("isin")).upper()
        if caja and caja in by_caja: return by_caja[caja],"MATCH_BY_CAJA_CODE"
        if isin and isin in by_isin: return by_isin[isin],"MATCH_BY_CEDEAR_ISIN"
        if local in by_local: return local,"MATCH_BY_LOCAL_BYMA_SYMBOL"
        if underlying in ambiguous: return None,"AMBIGUOUS_UNDERLYING_SYMBOL"
        if underlying in by_underlying: return by_underlying[underlying],"MATCH_BY_UNDERLYING_SYMBOL"
        if local in ambiguous: return None,"AMBIGUOUS_LEGACY_SYMBOL"
        if local in by_underlying: return by_underlying[local],"MATCH_BY_LEGACY_UNDERLYING_SYMBOL"
        stable_identity=(bool(caja) and caja in official_cajas) or (bool(isin) and isin in official_isins)
        source_verified=str(row.get("caja_byma_status","")).upper() in {"VALIDATED_BYMA_LAUNCH","VALIDATED_OFFICIAL_IDENTITY","VALIDATED_BYMA"}
        mandate=bool(row.get("mandate_exception",False))
        if stable_identity and local and (source_verified or mandate): return local,"MATCH_BY_VERIFIED_STABLE_IDENTITY_SOURCE_SYMBOL"
        return None,"NO_STRUCTURED_OFFICIAL_IDENTITY_MATCH"
    resolved=out.apply(resolve,axis=1); out["legacy_cedear_ticker"]=out["cedear_ticker"].astype(str).str.upper(); out["cedear_byma_symbol"]=resolved.map(lambda x:x[0]); out["official_match_method"]=resolved.map(lambda x:x[1])
    def official_map(col):
        result={}
        for symbol,group in official[official["cedear_byma_symbol"].ne("")].groupby("cedear_byma_symbol"):
            values=[_norm(v) for v in group[col] if _norm(v)]
            if values: result[_norm_symbol(symbol)]=values[0]
        return result
    for col in ("country_of_origin","underlying_market_official","industry_sector_official"):
        mapping=official_map(col); out[col]=out["cedear_byma_symbol"].map(lambda s:mapping.get(_norm_symbol(s),""))
    out["issuer_country_source"]="COMAFI_COUNTRY_OF_ORIGIN"; out["underlying_market_source"]="COMAFI_MARKET_OF_UNDERLYING"; out["industry_sector_source"]="COMAFI_INDUSTRY_OR_SECTOR"
    out["comafi_program_active"]=out["cedear_byma_symbol"].notna(); out["byma_tradability_status"]="BYMA_UNRESOLVED"
    confirmed=out["cedear_byma_symbol"].map(lambda s:bool(s) and (_norm_symbol(s) in audit.byma_symbols)); source_stable=out["official_match_method"].eq("MATCH_BY_VERIFIED_STABLE_IDENTITY_SOURCE_SYMBOL"); confirmed=confirmed | source_stable
    out.loc[confirmed,"byma_tradability_status"]="BYMA_CONFIRMED"; out["byma_tradable"]=out["byma_tradability_status"].eq("BYMA_CONFIRMED"); out["official_identity_verified_at"]=audit.verified_at; out["byma_evidence_mode"]=audit.byma_evidence_mode; out["official_identity_status"]="OFFICIAL_RECONCILIATION_UNRESOLVED"; out.loc[out["comafi_program_active"] & out["byma_tradable"],"official_identity_status"]="OFFICIAL_ISSUER_BYMA_VERIFIED"
    mandate=out.get("mandate_exception",pd.Series(False,index=out.index)).eq(True); out.loc[mandate & ~out["byma_tradable"],"official_identity_status"]="MANDATE_EXCEPTION_NOT_BYMA_CONFIRMED"; out["eligible_for_research"]=out["eligible"].eq(True) & ((out["comafi_program_active"] & out["byma_tradable"]) | mandate); out["eligibility_reason"]=out["official_identity_status"]
    return out
