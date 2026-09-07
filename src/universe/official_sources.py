from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

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


def _rename_catalog_columns(table: pd.DataFrame) -> pd.DataFrame:
    rename: dict[object, str] = {}
    for col in table.columns:
        key = _norm(col).lower()
        if "identificación" in key and "mercado" in key or "identificacion" in key and "mercado" in key:
            rename[col] = "cedear_byma_symbol"
        elif "denomin" in key or "programa" in key:
            rename[col] = "program_name"
        elif "código caja" in key or "codigo caja" in key:
            rename[col] = "caja_code"
    return table.rename(columns=rename)


def _parse_full_current_program_catalog(url: str) -> pd.DataFrame:
    response = _http_get(url)
    tables = pd.read_html(io.StringIO(response.text))
    candidates: list[pd.DataFrame] = []
    for table in tables:
        if len(table) < 5:
            continue
        out = _rename_catalog_columns(table.copy())
        if "cedear_byma_symbol" not in out.columns:
            continue
        out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm_symbol)
        out = out[out["cedear_byma_symbol"].str.match(r"^[A-Z][A-Z0-9./-]{0,11}$", na=False)].copy()
        if len(out) < 5:
            continue
        if "program_name" not in out.columns:
            out["program_name"] = out["cedear_byma_symbol"]
        if "caja_code" in out.columns:
            out["caja_code"] = out["caja_code"].map(_norm)
        else:
            out["caja_code"] = ""
        out["underlying_symbol"] = out["cedear_byma_symbol"]
        out["official_source_url"] = url
        out["official_source_kind"] = "FULL_CURRENT_PROGRAM_CATALOG"
        candidates.append(out[["program_name","cedear_byma_symbol","underlying_symbol","caja_code","official_source_url","official_source_kind"]])
    if not candidates:
        raise RuntimeError(f"COMAFI_PARSE_ERROR: full current program catalogue not found at {url}")
    out = pd.concat(candidates, ignore_index=True)
    return out.drop_duplicates("cedear_byma_symbol").reset_index(drop=True)


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
            elif "código caja" in key or "codigo caja" in key:
                rename[col] = "caja_code"
        out = table.rename(columns=rename)
        required = {"program_name", "cedear_byma_symbol", "underlying_symbol"}
        if not required.issubset(out.columns):
            continue
        out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm_symbol)
        out["underlying_symbol"] = out["underlying_symbol"].map(_norm_symbol)
        if "caja_code" in out.columns:
            out["caja_code"] = out["caja_code"].map(_norm)
        else:
            out["caja_code"] = ""
        out = out[out["cedear_byma_symbol"].str.match(r"^[A-Z0-9./-]+$", na=False)].copy()
        out["official_source_url"] = url
        out["official_source_kind"] = "DETAILED_IDENTITY_TABLE"
        return out[["program_name","cedear_byma_symbol","underlying_symbol","caja_code","official_source_url","official_source_kind"]]
    raise RuntimeError(f"COMAFI_PARSE_ERROR: detailed identity table not found at {url}")


def fetch_comafi_programs() -> pd.DataFrame:
    # The 2258 page is the current full catalogue (>300 programs) and is therefore the
    # primary inventory source. The detailed Shares page enriches origin ticker mappings.
    catalog = _parse_full_current_program_catalog(COMAFI_PROGRAM_CATALOG_URL)
    try:
        detail = _parse_detailed_identity_table(COMAFI_SHARES_DETAIL_URL)
    except Exception:
        detail = pd.DataFrame(columns=catalog.columns)

    by_symbol = catalog.set_index("cedear_byma_symbol", drop=False)
    if not detail.empty:
        for row in detail.itertuples(index=False):
            symbol = row.cedear_byma_symbol
            if symbol in by_symbol.index:
                by_symbol.loc[symbol, "underlying_symbol"] = row.underlying_symbol
                if _norm(row.caja_code):
                    by_symbol.loc[symbol, "caja_code"] = _norm(row.caja_code)
                by_symbol.loc[symbol, "official_source_kind"] = "FULL_CATALOG_PLUS_DETAILED_IDENTITY"
            else:
                by_symbol.loc[symbol] = row
    return by_symbol.reset_index(drop=True)


def verify_byma_ceadars_product_page(url: str = BYMA_CEDEARS_URL) -> None:
    response = _http_get(url)
    text = re.sub(r"\s+", " ", response.text).lower()
    if "cedear" not in text or not any(token in text for token in ("negoci", "trading", "conversion")):
        raise RuntimeError("BYMA_PRODUCT_PAGE_VALIDATION_ERROR: CEDEAR market evidence not found")


def fetch_official_universe_audit() -> OfficialUniverseAudit:
    verify_byma_ceadars_product_page()
    comafi = fetch_comafi_programs()
    if len(comafi) < 300:
        raise RuntimeError(f"COMAFI_COVERAGE_ERROR: current catalogue unexpectedly small ({len(comafi)}); refusing to certify universe")
    return OfficialUniverseAudit(
        comafi=comafi,
        byma_symbols=set(comafi["cedear_byma_symbol"].astype(str)),
        verified_at=datetime.now(timezone.utc).isoformat(),
        byma_evidence_mode="BYMA_MARKET_AUTHORITY_PLUS_COMAFI_FULL_CURRENT_CATALOG",
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
    for code, group in comafi[comafi["caja_code"].astype(str).str.len() > 0].groupby("caja_code"):
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
    out["eligible_for_research"] = out["eligible"].eq(True) & ((out["comafi_program_active"] & out["byma_tradable"]) | mandate)
    out["eligibility_reason"] = out["official_identity_status"]
    return out
