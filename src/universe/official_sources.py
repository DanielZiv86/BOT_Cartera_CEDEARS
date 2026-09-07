from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

COMAFI_SHARES_URL = "https://www.comafi.com.ar/CEDEAR-SHARES-2254.note.aspx"
COMAFI_ETFS_URL = "https://www.comafi.com.ar/CEDEAR-ETF-2255.note.aspx"
BYMA_CEDEARS_URL = "https://www.byma.com.ar/productos/productos-financieros/cedears"


@dataclass(frozen=True)
class OfficialUniverseAudit:
    comafi: pd.DataFrame
    byma_symbols: set[str]
    verified_at: str
    byma_evidence_mode: str = "STRUCTURED_COMAFI_BYMA_LISTING"


def _norm(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_symbol(value: object) -> str:
    return _norm(value).upper().replace(" ", "")


def _parse_comafi_table(url: str) -> pd.DataFrame:
    response = requests.get(url, timeout=30, headers={"User-Agent": "CEDEAR-MVP/1.0"})
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    wanted = None
    for table in tables:
        names = {_norm(c).lower() for c in table.columns}
        has_byma = any("símbolo byma" in n or "simbolo byma" in n or "id de mercado" in n for n in names)
        has_origin = any("ticker" in n and ("origen" in n or "mercado" in n) for n in names)
        if has_byma and has_origin:
            wanted = table.copy()
            break
    if wanted is None:
        raise RuntimeError(f"COMAFI_PARSE_ERROR: structured BYMA/ticker table not found at {url}")

    rename: dict[object, str] = {}
    for col in wanted.columns:
        key = _norm(col).lower()
        if "programa" in key or "denominación" in key or "denominacion" in key:
            rename[col] = "program_name"
        elif "símbolo byma" in key or "simbolo byma" in key or "id de mercado" in key:
            rename[col] = "cedear_byma_symbol"
        elif "ticker" in key and ("origen" in key or "mercado" in key):
            rename[col] = "underlying_symbol"
        elif "ratio" in key:
            rename[col] = "ratio_raw_official"
        elif "código caja" in key or "codigo caja" in key:
            rename[col] = "caja_code"
        elif "mercado de origen" in key or "mercado de valor subyacente" in key:
            rename[col] = "underlying_market_official"

    out = wanted.rename(columns=rename)
    required = {"program_name", "cedear_byma_symbol", "underlying_symbol"}
    if not required.issubset(out.columns):
        raise RuntimeError(f"COMAFI_SCHEMA_ERROR: missing {sorted(required-set(out.columns))} at {url}")
    out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm_symbol)
    out["underlying_symbol"] = out["underlying_symbol"].map(_norm_symbol)
    out = out[
        out["cedear_byma_symbol"].str.match(r"^[A-Z0-9./-]+$", na=False)
        & out["underlying_symbol"].str.match(r"^[A-Z0-9./-]+$", na=False)
    ].copy()
    out["official_source_url"] = url
    return out


def fetch_comafi_programs() -> pd.DataFrame:
    frames = []
    errors = []
    for url in (COMAFI_SHARES_URL, COMAFI_ETFS_URL):
        try:
            frames.append(_parse_comafi_table(url))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if not frames:
        raise RuntimeError("COMAFI_PARSE_ERROR: no structured official tables available; " + " | ".join(errors))
    out = pd.concat(frames, ignore_index=True)
    conflicts = out.groupby("cedear_byma_symbol")["underlying_symbol"].nunique()
    bad = conflicts[conflicts > 1]
    if not bad.empty:
        raise RuntimeError(f"COMAFI_IDENTITY_CONFLICT: {bad.index.tolist()}")
    return out.drop_duplicates("cedear_byma_symbol").reset_index(drop=True)


def verify_byma_ceadars_product_page(url: str = BYMA_CEDEARS_URL) -> None:
    response = requests.get(url, timeout=30, headers={"User-Agent": "CEDEAR-MVP/1.0"})
    response.raise_for_status()
    text = re.sub(r"\s+", " ", response.text).lower()
    if "cedear" not in text or not any(token in text for token in ("negoci", "trading", "conversion")):
        raise RuntimeError("BYMA_PRODUCT_PAGE_VALIDATION_ERROR: CEDEAR trading/listing evidence not found")


def fetch_official_universe_audit() -> OfficialUniverseAudit:
    # BYMA's product page is the market-level authority that CEDEARs are traded/listed
    # on BYMA. Instrument identity comes from Comafi's structured official tables,
    # which explicitly expose the local BYMA symbol and the origin-market ticker.
    # This deliberately replaces the former PDF-wide uppercase-token regex, which
    # generated false negatives and false positives from headings, prose and ratios.
    verify_byma_ceadars_product_page()
    comafi = fetch_comafi_programs()
    return OfficialUniverseAudit(
        comafi=comafi,
        byma_symbols=set(comafi["cedear_byma_symbol"].astype(str)),
        verified_at=datetime.now(timezone.utc).isoformat(),
        byma_evidence_mode="BYMA_PRODUCT_PAGE_PLUS_COMAFI_STRUCTURED_LOCAL_SYMBOL",
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

    def resolve(row: pd.Series) -> tuple[str | None, str]:
        local = _norm_symbol(row.get("cedear_ticker"))
        underlying = _norm_symbol(row.get("underlying_ticker"))
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

    # Mandate exceptions (currently IWDA) remain in-scope by explicit user mandate.
    # They are not falsely labelled BYMA-confirmed; instead their exception status is
    # explicit and auditable, while still allowing Research to consume them.
    mandate = out.get("mandate_exception", pd.Series(False, index=out.index)).eq(True)
    out.loc[mandate & ~out["byma_tradable"], "official_identity_status"] = "MANDATE_EXCEPTION_NOT_BYMA_CONFIRMED"
    out["eligible_for_research"] = out["eligible"].eq(True) & (
        (out["comafi_program_active"] & out["byma_tradable"]) | mandate
    )
    out["eligibility_reason"] = out["official_identity_status"]
    return out
