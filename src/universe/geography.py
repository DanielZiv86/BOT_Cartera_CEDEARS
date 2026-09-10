from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_geography_policy(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not payload.get("allowed_issuer_countries"):
        raise ValueError("Geography policy must define allowed_issuer_countries")
    return payload


def _norm(value: object) -> str:
    text=str(value or "").strip().upper()
    return "".join(c for c in unicodedata.normalize("NFKD",text) if not unicodedata.combining(c))

COUNTRY_ALIASES={
    "ESTADOS UNIDOS":"US","UNITED STATES":"US","USA":"US","EEUU":"US","EE.UU.":"US",
    "REINO UNIDO":"GB","UNITED KINGDOM":"GB","GRAN BRETANA":"GB","INGLATERRA":"GB",
    "IRLANDA":"IE","IRELAND":"IE","ALEMANIA":"DE","GERMANY":"DE","FRANCIA":"FR","FRANCE":"FR",
    "ESPANA":"ES","SPAIN":"ES","ITALIA":"IT","ITALY":"IT","PAISES BAJOS":"NL","NETHERLANDS":"NL","HOLANDA":"NL",
    "BELGICA":"BE","BELGIUM":"BE","LUXEMBURGO":"LU","LUXEMBOURG":"LU","SUIZA":"CH","SWITZERLAND":"CH",
    "AUSTRIA":"AT","DINAMARCA":"DK","DENMARK":"DK","SUECIA":"SE","SWEDEN":"SE","NORUEGA":"NO","NORWAY":"NO",
    "FINLANDIA":"FI","FINLAND":"FI","PORTUGAL":"PT","GRECIA":"GR","GREECE":"GR","POLONIA":"PL","POLAND":"PL",
    "REPUBLICA CHECA":"CZ","CZECH REPUBLIC":"CZ","CHEQUIA":"CZ","RUMANIA":"RO","ROMANIA":"RO","HUNGRIA":"HU","HUNGARY":"HU","ISLANDIA":"IS","ICELAND":"IS",
    "BRASIL":"BR","BRAZIL":"BR","JAPON":"JP","JAPAN":"JP","CHINA":"CN","ARGENTINA":"AR","CANADA":"CA","MEXICO":"MX","INDIA":"IN","TAIWAN":"TW","COREA DEL SUR":"KR","SOUTH KOREA":"KR"
}

def _country_code(value: object) -> str:
    normalized=_norm(value)
    return COUNTRY_ALIASES.get(normalized,normalized)


def _is_caja_reconciled(row: pd.Series) -> bool:
    """True only when official reconciliation explicitly resolved the security by Caja code."""
    method=_norm(row.get("official_match_method"))
    return method == "MATCH_BY_CAJA_CODE"


def apply_geography_eligibility(frame: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    """V2.1 mandate: US-traded underlying and issuer origin in US or Europe.

    Issuer origin normally comes from Banco Comafi's official ``País`` / ``País de Origen``.
    By explicit user mandate, an otherwise eligible US-traded security whose country is blank
    may also be admitted when its official identity was reconciled specifically by Código Caja.
    This is recorded as a separate auditable eligibility reason and does not infer a country.
    US-listed fund vehicles are admitted by their verified US listing when Comafi leaves country blank.
    IWDA remains the sole explicit ticker-level mandate exception.
    """
    out=frame.copy()
    countries={_norm(k):str(v) for k,v in (policy.get("allowed_issuer_countries") or {}).items()}
    allowed_exchanges={_norm(x) for x in policy.get("allowed_us_exchanges",[])}
    exceptions={_norm(x) for x in policy.get("mandate_exceptions",[])}
    fund_types={_norm(x) for x in policy.get("us_listed_fund_instrument_types",[])}
    reasons=policy.get("reason_codes",{}) or {}
    allowed_regions={"UNITED_STATES","EUROPE"}
    geo_ok=[]; geo_reason=[]; regions=[]; normalized_countries=[]
    for _,row in out.iterrows():
        ticker=_norm(row.get("cedear_ticker") or row.get("legacy_cedear_ticker"))
        country=_country_code(row.get("issuer_country"))
        exchange=_norm(row.get("underlying_market"))
        instrument_type=_norm(row.get("instrument_type"))
        normalized_countries.append(country)
        if ticker in exceptions or bool(row.get("mandate_exception",False)):
            geo_ok.append(True); geo_reason.append(reasons.get("mandate_exception","EXPLICIT_USER_MANDATE_EXCEPTION")); regions.append("MANDATE_EXCEPTION"); continue
        if exchange not in allowed_exchanges:
            geo_ok.append(False); geo_reason.append(reasons.get("exchange_outside_mandate","UNDERLYING_NOT_US_TRADED")); regions.append(countries.get(country)); continue
        if not country and instrument_type in fund_types:
            geo_ok.append(True); geo_reason.append(reasons.get("us_listed_fund","US_LISTED_FUND_VEHICLE")); regions.append("UNITED_STATES_FUND_VEHICLE"); continue
        if not country and _is_caja_reconciled(row):
            geo_ok.append(True); geo_reason.append(reasons.get("caja_reconciled_unknown_country","CAJA_CODE_RECONCILED_USER_MANDATE")); regions.append("CAJA_RECONCILED_COUNTRY_UNKNOWN"); continue
        region=countries.get(country)
        if not country:
            geo_ok.append(False); geo_reason.append(reasons.get("country_unknown","ISSUER_COUNTRY_UNVERIFIED")); regions.append(None); continue
        if region not in allowed_regions:
            geo_ok.append(False); geo_reason.append(reasons.get("country_outside_mandate","ISSUER_OUTSIDE_US_EUROPE")); regions.append(region); continue
        geo_ok.append(True); geo_reason.append(reasons.get("eligible","ISSUER_US_OR_EUROPE_AND_US_TRADED")); regions.append(region)
    out["issuer_country_normalized"]=normalized_countries
    out["issuer_region"]=regions
    out["geography_eligible"]=geo_ok
    out["geography_eligibility_reason"]=geo_reason
    out["eligible_for_research"]=out["eligible_for_research"].eq(True) & out["geography_eligible"].eq(True)
    return out
