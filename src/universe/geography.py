from __future__ import annotations

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
    return str(value or "").strip().upper()


def apply_geography_eligibility(frame: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    """Apply the V2.1 issuer-domicile and US-trading mandate.

    ``issuer_country`` must be independently hydrated from provider company-profile
    evidence. Exchange location is never used as a proxy for issuer domicile.
    Unknown domicile fails closed, except explicit mandate exceptions (IWDA).
    """
    out = frame.copy()
    countries = {_norm(k): str(v) for k, v in (policy.get("allowed_issuer_countries") or {}).items()}
    allowed_exchanges = {_norm(x) for x in policy.get("allowed_us_exchanges", [])}
    exceptions = {_norm(x) for x in policy.get("mandate_exceptions", [])}
    reasons = policy.get("reason_codes", {}) or {}

    geo_ok: list[bool] = []
    geo_reason: list[str] = []
    regions: list[str | None] = []
    for _, row in out.iterrows():
        ticker = _norm(row.get("cedear_ticker") or row.get("legacy_cedear_ticker"))
        country = _norm(row.get("issuer_country"))
        exchange = _norm(row.get("underlying_market"))
        if ticker in exceptions or bool(row.get("mandate_exception", False)):
            geo_ok.append(True); geo_reason.append(reasons.get("mandate_exception", "EXPLICIT_USER_MANDATE_EXCEPTION")); regions.append("MANDATE_EXCEPTION"); continue
        region = countries.get(country)
        if not country or region is None:
            geo_ok.append(False); geo_reason.append(reasons.get("country_unknown", "ISSUER_COUNTRY_UNVERIFIED") if not country else reasons.get("country_outside_mandate", "ISSUER_OUTSIDE_US_EUROPE")); regions.append(None); continue
        if exchange not in allowed_exchanges:
            geo_ok.append(False); geo_reason.append(reasons.get("exchange_outside_mandate", "UNDERLYING_NOT_US_TRADED")); regions.append(region); continue
        geo_ok.append(True); geo_reason.append(reasons.get("eligible", "ISSUER_US_OR_EUROPE_AND_US_TRADED")); regions.append(region)

    out["issuer_region"] = regions
    out["geography_eligible"] = geo_ok
    out["geography_eligibility_reason"] = geo_reason
    out["eligible_for_research"] = out["eligible_for_research"].eq(True) & out["geography_eligible"].eq(True)
    return out
