from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests


class IssuerHoldingsError(RuntimeError):
    pass


@dataclass
class HoldingsSnapshot:
    ticker: str
    holdings: list[dict[str, Any]]
    as_of: str | None
    source_ref: str
    source_tier: str
    provider: str
    retrieval_status: str = "READY"


class IssuerHoldingsConnector:
    """Fetch and normalize ETF holdings from issuer pages or configured fallbacks.

    Sources are configured per ticker. Supported modes:
      - html_table: parse a holdings table from an HTML page.
      - ishares_csv: use the official iShares holdings CSV endpoint derived from a product page URL.

    A secondary HTML source can be configured, but its tier is always preserved as
    SECONDARY_HOLDINGS_FALLBACK so downstream confidence can be reduced.
    """

    def __init__(self, sources: dict[str, Any], timeout: int = 30):
        self.sources = {str(k).upper(): v for k, v in (sources or {}).items()}
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 CEDEAR-ETF-Valuation/1.0",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def fetch(self, ticker: str) -> HoldingsSnapshot:
        symbol = ticker.upper()
        cfg = self.sources.get(symbol)
        if not isinstance(cfg, dict):
            raise IssuerHoldingsError("ISSUER_SOURCE_NOT_CONFIGURED")

        attempts: list[str] = []
        primary = cfg.get("primary")
        if isinstance(primary, dict):
            try:
                return self._fetch_source(symbol, primary, "ISSUER_OFFICIAL")
            except Exception as exc:  # noqa: BLE001 - preserve provider fallback semantics
                attempts.append(f"PRIMARY:{type(exc).__name__}:{exc}")

        secondary = cfg.get("secondary")
        if isinstance(secondary, dict):
            try:
                return self._fetch_source(symbol, secondary, "SECONDARY_HOLDINGS_FALLBACK")
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"SECONDARY:{type(exc).__name__}:{exc}")

        raise IssuerHoldingsError(";".join(attempts) or "NO_USABLE_HOLDINGS_SOURCE")

    def _fetch_source(self, ticker: str, cfg: dict[str, Any], tier: str) -> HoldingsSnapshot:
        mode = str(cfg.get("mode") or "html_table").lower()
        url = str(cfg.get("url") or "").strip()
        if not url:
            raise IssuerHoldingsError("SOURCE_URL_MISSING")

        if mode == "ishares_csv":
            holdings, as_of = self._fetch_ishares_csv(url, ticker)
        elif mode == "html_table":
            holdings, as_of = self._fetch_html_table(url)
        else:
            raise IssuerHoldingsError(f"UNSUPPORTED_SOURCE_MODE:{mode}")

        if not holdings:
            raise IssuerHoldingsError("NO_HOLDINGS_PARSED")
        return HoldingsSnapshot(
            ticker=ticker,
            holdings=holdings,
            as_of=as_of,
            source_ref=url,
            source_tier=tier,
            provider=str(cfg.get("provider") or "UNKNOWN"),
        )

    def _get(self, url: str) -> requests.Response:
        response = requests.get(url, timeout=self.timeout, headers=self.headers)
        response.raise_for_status()
        return response

    def _fetch_ishares_csv(self, product_url: str, ticker: str) -> tuple[list[dict[str, Any]], str | None]:
        base = product_url.rstrip("/")
        csv_url = f"{base}/1467271812596.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
        response = self._get(csv_url)
        text = response.text
        lines = text.splitlines()
        header_idx = None
        for idx, line in enumerate(lines):
            upper = line.upper()
            if "TICKER" in upper and ("WEIGHT" in upper or "WEIGHT (%)" in upper):
                header_idx = idx
                break
        if header_idx is None:
            raise IssuerHoldingsError("ISHARES_CSV_HEADER_NOT_FOUND")
        frame = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
        holdings = self._normalize_table(frame)
        as_of = self._extract_date(text)
        return holdings, as_of

    def _fetch_html_table(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        response = self._get(url)
        text = response.text
        tables = pd.read_html(io.StringIO(text))
        best: list[dict[str, Any]] = []
        for table in tables:
            normalized = self._normalize_table(table)
            if len(normalized) > len(best):
                best = normalized
        return best, self._extract_date(text)

    @staticmethod
    def _normalize_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        df = frame.copy()
        df.columns = [str(c).strip() for c in df.columns]
        lower = {str(c).strip().lower(): c for c in df.columns}

        ticker_col = next((orig for key, orig in lower.items() if key in {"ticker", "symbol"} or "ticker" in key), None)
        weight_col = next((orig for key, orig in lower.items() if "weight" in key or "% of fund" in key or "% of net assets" in key or "holding percent" in key), None)
        if ticker_col is None or weight_col is None:
            return []

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            symbol = str(row.get(ticker_col) or "").strip().upper()
            if not symbol or symbol in {"NAN", "--", "-", "CASH", "USD"} or "CASH" in symbol:
                continue
            raw_weight = str(row.get(weight_col) or "").replace("%", "").replace(",", "").strip()
            try:
                weight = float(raw_weight)
            except ValueError:
                continue
            if weight <= 0:
                continue
            if weight <= 1.0 and "%" not in str(row.get(weight_col)):
                # Most issuer tables publish percentage points; preserve fractional
                # values only when they clearly sum like decimals downstream.
                pass
            rows.append({"symbol": symbol, "percent": weight})
        return rows

    @staticmethod
    def _extract_date(text: str) -> str | None:
        patterns = [
            r"(?:as of|holdings as of|daily holdings .*? as of)\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"(?:as of|holdings as of)\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:as of|holdings as of)\s*(\d{4}-\d{2}-\d{2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1)
            for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt).date().isoformat()
                except ValueError:
                    pass
        return None

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()
