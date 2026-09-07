from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

# Comafi currently exposes more than one public representation of its CEDEAR universe.
# The legacy detailed Shares table is useful for local-vs-origin symbol mapping, while
# the Custodia Global program catalogue is the broader current inventory and includes
# Shares and ETFs.  We intentionally reconcile the union rather than treating failure
# of one legacy detail page as evidence that a program is not current.
COMAFI_SHARES_DETAIL_URL = "https://www.comafi.com.ar/CEDEAR-SHARES-2254.note.aspx"
COMAFI_PROGRAM_CATALOG_URL = "https://www.comafi.com.ar/CEDEARs-2258.note.aspx"
COMAFI_PROGRAMS_URL = "https://www.comafi.com.ar/custodiaglobal/programas.aspx"
BYMA_CEDEARS_URL = "https://www.byma.com.ar/productos/productos-financieros/cedears"


@dataclass(frozen=True)
class OfficialUniverseAudit:
    comafi: pd.DataFrame
    byma_symbols: set[str]
    verified_at: str
    byma_evidence_mode: str = "TEST_OR_LEGACY_STRUCTURED_EVIDENCE"


def _norm(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_symbol(value: object) -> str:
    return _norm(value).upper().replace(" ", "")


def _http_get(url: str) -> requests.Response:
    response = requests.get(url, timeout=30, headers={"User-Agent": "CEDEAR-MVP/1.0"})
    response.raise_for_status()
    return response


def _parse_detailed_identity_table(url: str) -> pd.DataFrame:
    response = _http_get(url)
    tables = pd.read_html(io.StringIO(response.text))
    for table in tables:
        names = {_norm(c).lower() for c in table.columns}
        has_byma = any("símbolo byma" in n or "simbolo byma" in n for n in names)
        has_origin = any("ticker" in n and ("origen" in n or "mercado" in n) for n in names)
        if not (has_byma and has_origin):
            continue
        rename: dict[object, str] = {}
        for col in table.columns:
            key = _norm(col).lower()
            if "programa" in key or "denominación" in key or "denominacion" in key:
                rename[col] = "program_name"
            elif "símbolo byma" in key or "simbolo byma" in key:
                rename[col] = "cedear_byma_symbol"
            elif "ticker" in key and ("origen" in key or "mercado" in key):
                rename[col] = "underlying_symbol"
            elif "ratio" in key:
                rename[col] = "ratio_raw_official"
            elif "código caja" in key or "codigo caja" in key:
                rename[col] = "caja_code"
        out = table.rename(columns=rename)
        required = {"program_name", "cedear_byma_symbol", "underlying_symbol"}
        if not required.issubset(out.columns):
            continue
        out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm_symbol)
        out["underlying_symbol"] = out["underlying_symbol"].map(_norm_symbol)
        out = out[out["cedear_byma_symbol"].str.match(r"^[A-Z0-9./-]+$", na=False)].copy()
        out["official_source_url"] = url
        out["official_source_kind"] = "DETAILED_IDENTITY_TABLE"
        return out
    raise RuntimeError(f"COMAFI_PARSE_ERROR: detailed identity table not found at {url}")


def _parse_current_program_catalog(url: str) -> pd.DataFrame:
    response = _http_get(url)
    tables = pd.read_html(io.StringIO(response.text))
    candidates: list[pd.DataFrame] = []
    for table in tables:
        if len(table) < 5:
            continue
        cols = list(table.columns)
        rename: dict[object, str] = {}
        for col in cols:
            key = _norm(col).lower()
            if any(x in key for x in ("identificación mercado", "identificacion mercado", "símbolo", "simbolo", "ticker")):
                rename[col] = "cedear_byma_symbol"
            elif "denomin" in key or "programa" in key:
                rename[col] = "program_name"
            elif "código caja" in key or "codigo caja" in key:
                rename[col] = "caja_code"
        out = table.rename(columns=rename)
        if "cedear_byma_symbol" not in out.columns:
            first = out.columns[0]
            vals = out[first].map(_norm_symbol)
            ratio = vals.str.match(r"^[A-Z][A-Z0-9./-]{0,9}$", na=False).mean()
            if ratio >= 0.70:
                out = out.rename(columns={first: "cedear_byma_symbol"})
        if "cedear_byma_symbol" not in out.columns:
            continue
        out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm_symbol)
        out = out[out["cedear_byma_symbol"].str.match(r"^[A-Z][A-Z0-9./-]{0,9}$", na=False)].copy()
        if len(out) < 5:
            continue
        if "program_name" not in out.columns:
            out["program_name"] = out["cedear_byma_symbol"]
        out["underlying_symbol"] = out["cedear_byma_symbol"]
        out["official_source_url"] = url
        out["official_source_kind"] = "CURRENT_PROGRAM_CATALOG"
        candidates.append(out)
    if not candidates:
        raise RuntimeError(f"COMAFI_PARSE_ERROR: current program catalogue not found at {url}")
    return pd.concat(candidates, ignore_index=True)


def fetch_comafi_programs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for parser, url in (
        (_parse_current_program_catalog, COMAFI_PROGRAM_CATALOG_URL),
        (_parse_detailed_identity_table, COMAFI_SHARES_DETAIL_URL),
    ):
        try:
            frames.append(parser(url))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if not frames:
        raise RuntimeError("COMAFI_PARSE_ERROR: no official program source available; " + " | ".join(errors))

    raw = pd.concat(frames, ignore_index=True, sort=False)
    raw["cedear_byma_symbol"] = raw["cedear_byma_symbol"].map(_norm_symbol)
    raw["underlying_symbol"] = raw["underlying_symbol"].map(_norm_symbol)
    priority = {"DETAILED_IDENTITY_TABLE": 0, "CURRENT_PROGRAM_CATALOG": 1}
    raw["_priority"] = raw["official_source_kind"].map(priority).fillna(9)
    raw = raw.sort_values(["cedear_byma_symbol", "_priority"])
    out = raw.drop_duplicates("cedear_byma_symbol", keep="first").drop(columns=["_priority"])
    return out.reset_index(drop=True)


def verify_byma_ceadars_product_page(url: str = BYMA_CEDEARS_URL) -> None:
    response = _http_get(url)
    text = re.sub(r"\s+", " ", response.text).lower()
    if "cedear" not in text or not any(token in text for token in ("negoci", "trading", "conversion")):
        raise RuntimeError("BYMA_PRODUCT_PAGE_VALIDATION_ERROR: CEDEAR market evidence not found")


def fetch_official_universe_audit() -> OfficialUniverseAudit:
    verify_byma_ceadars_product_page()
    comafi = fetch_comafi_programs()
    return OfficialUniverseAudit(
        comafi=comafi,
        byma_symbols=set(comafi["cedear_byma_symbol"].astype(str)),
        verified_at=datetime.now(timezone.utc).isoformat(),
        byma_evidence_mode="BYMA_MARKET_AUTHORITY_PLUS_CURRENT_COMAFI_PROGRAM_CATALOG",
    )


def reconcile_official_identity(source: pd.DataFrame, audit: OfficialUniverseAudit) -> pd.DataFrame:
    out = source.copy()
    comafi = audit.comafi.copy()
    by_local = set(comafi["cedear_byma_symbol"])
    by_underlying: dict[str, str] = {}
    ambiguous_underlyings: set[str] = set()
    for underlying, group in comafi.groupby("underlying_symbol"):
        symbols = sorted(set(group["cedear_byma_symbol"].astype(str)))
        if len(symbols) == 1:
            by_underlying[str(underlying)] = symbols[0]
        else:
            ambiguous_underlyings.add(str(underlying))

    by_caja: dict[str, str] = {}
    if "caja_code" in comafi.columns:
        for code, group in comafi.dropna(subset=["caja_code"]).groupby("caja_code"):
            symbols = sorted(set(group["cedear_byma_symbol"].astype(str)))
            if len(symbols) == 1:
                by_caja[_norm(code)] = symbols[0]

    def resolve(row: pd.Series) -> tuple[str | None, str]:
        local = _norm_symbol(row.get("cedear_ticker"))
        underlying = _norm_symbol(row.get("underlying_ticker"))
        caja = _norm(row.get("caja_code"))
        if caja and caja in by_caja:
            return by_caja[caja], "MATCH_BY_CAJA_CODE"
        if local in by_local:
            return local, "MATCH_BY_LOCAL_BYMA_SYMBOL"
        if underlying in ambiguous_underlyings:
            return None, "AMBIGUOUS_UNDERLYING_SYMBOL"
        if underlying in by_underlying:
            return by_underlying[underlying], "MATCH_BY_UNDERLYING_SYMBOL"
        if local in ambiguous_underlyings:
            return None, "AMBIGUOUS_LEGACY_SYMBOL"
        if local in by_underlying:
            return by_underlying[local], "MATCH_BY_LEGACY_UNDERLYING_SYMBOL"
        return None, "NO_STRUCTURED_OFFICIAL_IDENTITY_MATCH"

    resolved = out.apply(resolve, axis=1)
    out["legacy_cedear_ticker"] = out["cedear_ticker"].astype(str).str.upper()
    out["cedear_byma_symbol"] = resolved.map(lambda x: x[0])
    out["official_match_method"] = resolved.map(lambda x: x[1])
    out["comafi_program_active"] = out["cedear_byma_symbol"].notna()
    out["byma_tradability_status"] = "BYMA_UNRESOLVED"
    confirmed = out["cedear_byma_symbol"].map(lambda s: bool(s) and _norm_symbol(s) in audit.byma_symbols)
    out.loc[confirmed, "byma_tradability_status"] = "BYMA_CONFIRMED"
    out["byma_tradable"] = out["byma_tradability_status"].eq("BYMA_CONFIRMED")
    out["official_identity_verified_at"] = audit.verified_at
    out["byma_evidence_mode"] = audit.byma_evidence_mode
    out["official_identity_status"] = "OFFICIAL_RECONCILIATION_UNRESOLVED"
    out.loc[out["comafi_program_active"] & out["byma_tradable"], "official_identity_status"] = "COMAFI_BYMA_VERIFIED"

    mandate = out.get("mandate_exception", pd.Series(False, index=out.index)).eq(True)
    out.loc[mandate & ~out["byma_tradable"], "official_identity_status"] = "MANDATE_EXCEPTION_NOT_BYMA_CONFIRMED"
    out["eligible_for_research"] = out["eligible"].eq(True) & (
        (out["comafi_program_active"] & out["byma_tradable"]) | mandate
    )
    out["eligibility_reason"] = out["official_identity_status"]
    return out
