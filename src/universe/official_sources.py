from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests
from pypdf import PdfReader

COMAFI_SHARES_URL = "https://www.comafi.com.ar/CEDEAR-SHARES-2254.note.aspx"
BYMA_CEDEARS_PDF_URL = "https://cdn.prod.website-files.com/6697a441a50c6b926e1972e0/6a99db1932a470f0a32b5e8a_BYMA-CEDEARs-2026-09-03.pdf"


@dataclass(frozen=True)
class OfficialUniverseAudit:
    comafi: pd.DataFrame
    byma_symbols: set[str]
    verified_at: str


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fetch_comafi_programs(url: str = COMAFI_SHARES_URL) -> pd.DataFrame:
    response = requests.get(url, timeout=30, headers={"User-Agent": "CEDEAR-MVP/1.0"})
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    wanted = None
    for table in tables:
        names = {_norm(c).lower() for c in table.columns}
        if any("símbolo byma" in n or "simbolo byma" in n for n in names) and any("ticker" in n and "origen" in n for n in names):
            wanted = table.copy(); break
    if wanted is None:
        raise RuntimeError("COMAFI_PARSE_ERROR: official table with BYMA symbol was not found")
    rename = {}
    for col in wanted.columns:
        key = _norm(col).lower()
        if "programa" in key: rename[col] = "program_name"
        elif "símbolo byma" in key or "simbolo byma" in key: rename[col] = "cedear_byma_symbol"
        elif "ticker" in key and "origen" in key: rename[col] = "underlying_symbol"
        elif "ratio" in key: rename[col] = "ratio_raw_official"
        elif "código caja" in key or "codigo caja" in key: rename[col] = "caja_code"
    out = wanted.rename(columns=rename)
    required = {"program_name", "cedear_byma_symbol", "underlying_symbol"}
    if not required.issubset(out.columns):
        raise RuntimeError(f"COMAFI_SCHEMA_ERROR: missing {sorted(required-set(out.columns))}")
    out["cedear_byma_symbol"] = out["cedear_byma_symbol"].map(_norm).str.upper()
    out["underlying_symbol"] = out["underlying_symbol"].map(_norm).str.upper()
    out = out[out["cedear_byma_symbol"].str.match(r"^[A-Z0-9./-]+$", na=False)].copy()
    return out.drop_duplicates("cedear_byma_symbol").reset_index(drop=True)


def fetch_byma_tradable_symbols(url: str = BYMA_CEDEARS_PDF_URL) -> set[str]:
    response = requests.get(url, timeout=45, headers={"User-Agent": "CEDEAR-MVP/1.0"})
    response.raise_for_status()
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text) < 1000:
        raise RuntimeError("BYMA_PARSE_ERROR: official negotiable CEDEAR PDF yielded insufficient text")
    # Membership is reconciled only against official Comafi symbols downstream; this broad
    # token extraction deliberately does not invent instruments from arbitrary PDF tokens.
    return set(re.findall(r"(?<![A-Z0-9])[A-Z][A-Z0-9./-]{1,9}(?![A-Z0-9])", text.upper()))


def fetch_official_universe_audit() -> OfficialUniverseAudit:
    return OfficialUniverseAudit(
        comafi=fetch_comafi_programs(),
        byma_symbols=fetch_byma_tradable_symbols(),
        verified_at=datetime.now(timezone.utc).isoformat(),
    )


def reconcile_official_identity(source: pd.DataFrame, audit: OfficialUniverseAudit) -> pd.DataFrame:
    out = source.copy()
    comafi = audit.comafi.copy()
    by_underlying = {r.underlying_symbol: r.cedear_byma_symbol for r in comafi.itertuples()}
    by_local = set(comafi["cedear_byma_symbol"])

    def resolve(row: pd.Series) -> str | None:
        local = _norm(row.get("cedear_ticker")).upper()
        underlying = _norm(row.get("underlying_ticker")).upper()
        if local in by_local: return local
        return by_underlying.get(underlying) or by_underlying.get(local)

    out["legacy_cedear_ticker"] = out["cedear_ticker"].astype(str).str.upper()
    out["cedear_byma_symbol"] = out.apply(resolve, axis=1)
    out["comafi_program_active"] = out["cedear_byma_symbol"].notna()
    out["byma_tradable"] = out["cedear_byma_symbol"].map(lambda s: bool(s) and str(s).upper() in audit.byma_symbols)
    out["official_identity_verified_at"] = audit.verified_at
    out["official_identity_status"] = "OFFICIAL_RECONCILIATION_FAILED"
    out.loc[out["comafi_program_active"] & out["byma_tradable"], "official_identity_status"] = "COMAFI_BYMA_VERIFIED"
    # IWDA is a mandate exception to the underlying-market rule, not to local tradability.
    out["eligible_for_research"] = out["eligible"].eq(True) & out["comafi_program_active"] & out["byma_tradable"]
    out["eligibility_reason"] = out["official_identity_status"]
    return out
