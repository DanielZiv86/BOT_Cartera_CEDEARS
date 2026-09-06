from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
    freshness_max_age_days: int | None = None
    max_holdings_to_analyze: int | None = None


class IssuerHoldingsConnector:
    """Fetch and normalize ETF holdings from issuer pages or configured fallbacks."""

    def __init__(self, sources: dict[str, Any], timeout: int = 30):
        self.sources = {str(k).upper(): v for k, v in (sources or {}).items()}
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 CEDEAR-ETF-Valuation/1.3",
            "Accept-Language": "en-US,en;q=0.9",
        }
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self._cache: dict[str, HoldingsSnapshot] = {}
        self._errors: dict[str, str] = {}

    def fetch(self, ticker: str) -> HoldingsSnapshot:
        symbol = ticker.upper()
        if symbol in self._cache:
            return self._cache[symbol]
        if symbol in self._errors:
            raise IssuerHoldingsError(self._errors[symbol])

        cfg = self.sources.get(symbol)
        if not isinstance(cfg, dict):
            raise IssuerHoldingsError("ISSUER_SOURCE_NOT_CONFIGURED")

        attempts: list[str] = []
        primary = cfg.get("primary")
        primary_meta = primary if isinstance(primary, dict) else {}
        if isinstance(primary, dict):
            try:
                snapshot = self._fetch_source(symbol, primary, "ISSUER_OFFICIAL")
                self._cache[symbol] = snapshot
                return snapshot
            except Exception as exc:  # noqa: BLE001
                primary_error = f"PRIMARY:{type(exc).__name__}:{exc}"
                attempts.append(primary_error)
                if str(primary.get("provider") or "").strip().lower() == "vanguard":
                    print(f"VANGUARD_PRIMARY_DIAGNOSTIC ticker={symbol} error={primary_error}")

        secondary = cfg.get("secondary")
        if isinstance(secondary, dict):
            inherited = dict(secondary)
            for key in ("max_age_days", "max_holdings_to_analyze"):
                if inherited.get(key) is None and primary_meta.get(key) is not None:
                    inherited[key] = primary_meta[key]
            try:
                snapshot = self._fetch_source(symbol, inherited, "SECONDARY_HOLDINGS_FALLBACK")
                self._cache[symbol] = snapshot
                return snapshot
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"SECONDARY:{type(exc).__name__}:{exc}")

        message = ";".join(attempts) or "NO_USABLE_HOLDINGS_SOURCE"
        self._errors[symbol] = message
        raise IssuerHoldingsError(message)

    def _fetch_source(self, ticker: str, cfg: dict[str, Any], tier: str) -> HoldingsSnapshot:
        mode = str(cfg.get("mode") or "html_table").lower()
        url = str(cfg.get("url") or "").strip()
        if not url:
            raise IssuerHoldingsError("SOURCE_URL_MISSING")

        if mode == "ishares_csv":
            holdings, as_of = self._fetch_ishares_csv(url, ticker)
        elif mode == "ishares_ucits_html":
            holdings, as_of = self._fetch_ishares_ucits_html(url)
        elif mode == "vanguard_html":
            holdings, as_of = self._fetch_vanguard_html(url)
        elif mode == "html_table":
            holdings, as_of = self._fetch_html_table(url)
        else:
            raise IssuerHoldingsError(f"UNSUPPORTED_SOURCE_MODE:{mode}")

        if not holdings:
            raise IssuerHoldingsError("NO_HOLDINGS_PARSED")
        freshness_override = cfg.get("max_age_days")
        holdings_limit = cfg.get("max_holdings_to_analyze")
        return HoldingsSnapshot(
            ticker=ticker,
            holdings=holdings,
            as_of=as_of,
            source_ref=url,
            source_tier=tier,
            provider=str(cfg.get("provider") or "UNKNOWN"),
            freshness_max_age_days=int(freshness_override) if freshness_override is not None else None,
            max_holdings_to_analyze=int(holdings_limit) if holdings_limit is not None else None,
        )

    def _get(self, url: str) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                _ = response.content
                return response
            except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(float(attempt))
        if last_exc is not None:
            raise last_exc
        raise IssuerHoldingsError("HTTP_RETRIEVAL_FAILED")

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

    def _fetch_ishares_ucits_html(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        response = self._get(url)
        text = response.text
        tables = pd.read_html(io.StringIO(text))
        candidates: list[tuple[int, list[dict[str, Any]]]] = []
        for table in tables:
            normalized = self._normalize_table(table)
            if normalized:
                cols = " ".join(str(c).lower() for c in table.columns)
                score = len(normalized) + (10000 if "issuer ticker" in cols and "weight" in cols else 0)
                candidates.append((score, normalized))
        if not candidates:
            raise IssuerHoldingsError("ISHARES_UCITS_HOLDINGS_TABLE_NOT_FOUND")
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], self._extract_date(text)

    def _fetch_vanguard_html(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        """Select Vanguard's actual holdings table and expose minimal acquisition diagnostics."""
        response = self._get(url)
        text = response.text
        try:
            tables = pd.read_html(io.StringIO(text))
        except Exception as exc:  # noqa: BLE001
            print(
                "VANGUARD_HTTP_DIAGNOSTIC "
                f"status={response.status_code} html_bytes={len(response.content)} "
                f"table_parse_error={type(exc).__name__}:{exc}"
            )
            raise

        column_sets = [[str(c).strip() for c in table.columns] for table in tables]
        print(
            "VANGUARD_HTTP_DIAGNOSTIC "
            f"status={response.status_code} html_bytes={len(response.content)} "
            f"tables={len(tables)} columns={column_sets}"
        )

        candidates: list[tuple[int, list[dict[str, Any]]]] = []
        for table in tables:
            columns = [str(c).strip().lower() for c in table.columns]
            has_holdings = any(c in {"holding", "holdings"} for c in columns)
            has_fund_weight = any("% of fund" in c or "% of funds" in c for c in columns)
            if not (has_holdings and has_fund_weight):
                continue
            normalized = self._normalize_table(table)
            if normalized:
                candidates.append((len(normalized), normalized))
        if not candidates:
            raise IssuerHoldingsError("VANGUARD_HOLDINGS_TABLE_NOT_FOUND")
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], self._extract_date(text)

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

        ticker_col = next((orig for key, orig in lower.items() if key in {"ticker", "symbol", "issuer ticker"} or "ticker" in key), None)
        holdings_name_col = next((orig for key, orig in lower.items() if key in {"holding", "holdings"}), None)
        weight_col = next((orig for key, orig in lower.items() if "weight" in key or "% of fund" in key or "% of funds" in key or "% of net assets" in key or "holding percent" in key), None)
        if (ticker_col is None and holdings_name_col is None) or weight_col is None:
            return []

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            if ticker_col is not None:
                symbol = str(row.get(ticker_col) or "").strip().upper()
            else:
                holding_name = str(row.get(holdings_name_col) or "").strip()
                match = re.search(r"\(([A-Za-z0-9.\-/]+)\)\s*$", holding_name)
                symbol = match.group(1).upper() if match else ""
            if not symbol or symbol in {"NAN", "--", "-", "CASH", "USD"} or "CASH" in symbol:
                continue
            raw_weight = str(row.get(weight_col) or "").replace("%", "").replace(",", "").strip()
            try:
                weight = float(raw_weight)
            except ValueError:
                continue
            if weight <= 0:
                continue
            rows.append({"symbol": symbol, "percent": weight})
        return rows

    @staticmethod
    def _extract_date(text: str) -> str | None:
        patterns = [
            r"(?:as of|holdings as of|daily holdings .*? as of)\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"(?:as of|holdings as of|daily holdings \(%\) as of)\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:as of|holdings as of)\s*(\d{4}-\d{2}-\d{2})",
            r"(?:as of|holdings as of)\s*(\d{1,2}/[A-Za-z]{3,9]/\d{4})",
        ]
        dates: list[datetime] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = match.group(1)
                for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d/%b/%Y", "%d/%B/%Y"):
                    try:
                        dates.append(datetime.strptime(value, fmt))
                        break
                    except ValueError:
                        pass
        return max(dates).date().isoformat() if dates else None

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()
