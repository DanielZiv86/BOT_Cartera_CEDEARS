from __future__ import annotations

import html
import io
import json
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

    VANGUARD_BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://advisors.vanguard.com/",
    }

    def __init__(self, sources: dict[str, Any], timeout: int = 30):
        self.sources = {str(k).upper(): v for k, v in (sources or {}).items()}
        self.timeout = timeout
        self.headers = {"User-Agent": "Mozilla/5.0 CEDEAR-ETF-Valuation/1.4", "Accept-Language": "en-US,en;q=0.9"}
        retry = Retry(total=3, connect=3, read=3, status=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)
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
        source_ref = url
        if mode == "ishares_csv":
            holdings, as_of = self._fetch_ishares_csv(url, ticker)
        elif mode == "ishares_ucits_html":
            holdings, as_of = self._fetch_ishares_ucits_html(url)
        elif mode in {"vanguard_html", "vanguard_json"}:
            holdings, as_of, source_ref = self._fetch_vanguard(ticker, url)
        elif mode == "html_table":
            holdings, as_of = self._fetch_html_table(url)
        else:
            raise IssuerHoldingsError(f"UNSUPPORTED_SOURCE_MODE:{mode}")
        if not holdings:
            raise IssuerHoldingsError("NO_HOLDINGS_PARSED")
        freshness_override = cfg.get("max_age_days")
        holdings_limit = cfg.get("max_holdings_to_analyze")
        return HoldingsSnapshot(ticker=ticker, holdings=holdings, as_of=as_of, source_ref=source_ref, source_tier=tier, provider=str(cfg.get("provider") or "UNKNOWN"), freshness_max_age_days=int(freshness_override) if freshness_override is not None else None, max_holdings_to_analyze=int(holdings_limit) if holdings_limit is not None else None)

    def _get(self, url: str, headers: dict[str, str] | None = None) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.session.get(url, timeout=self.timeout, headers=headers)
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

    def _fetch_vanguard(self, ticker: str, official_url: str) -> tuple[list[dict[str, Any]], str | None, str]:
        """Prefer Vanguard JSON, then recover holdings from official advisor HTML/state."""
        try:
            return self._fetch_vanguard_json(ticker)
        except Exception as json_exc:  # noqa: BLE001
            print(f"VANGUARD_JSON_FALLBACK ticker={ticker.upper()} reason={type(json_exc).__name__}:{json_exc}")
        response = self._get(official_url, headers={**self.VANGUARD_BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml"})
        text = response.text
        best: list[dict[str, Any]] = []
        try:
            tables = pd.read_html(io.StringIO(text))
        except ValueError:
            tables = []
        for table in tables:
            normalized = self._normalize_table(table)
            if len(normalized) > len(best):
                best = normalized
        if not best:
            best = self._extract_vanguard_embedded_holdings(text)
        as_of = self._extract_date(text)
        print(f"VANGUARD_HTML_DIAGNOSTIC ticker={ticker.upper()} holdings={len(best)} as_of={as_of}")
        if not best:
            raise IssuerHoldingsError("VANGUARD_HTML_NO_HOLDINGS")
        if as_of is None:
            raise IssuerHoldingsError("VANGUARD_HTML_AS_OF_MISSING")
        return best, as_of, official_url

    @classmethod
    def _extract_vanguard_embedded_holdings(cls, text: str) -> list[dict[str, Any]]:
        """Recover holdings rendered client-side by Vanguard from embedded page state/text.

        Vanguard advisor pages can contain the holdings payload without a literal HTML table.
        This parser is deliberately schema-tolerant but conservative: it only accepts a
        symbol paired with an explicit positive percentage and de-duplicates by symbol.
        """
        decoded = html.unescape(text).replace("\\u0025", "%")
        decoded = re.sub(r"<[^>]+>", " ", decoded)
        decoded = re.sub(r"\\[nrt]", " ", decoded)
        decoded = re.sub(r"\s+", " ", decoded)
        found: dict[str, float] = {}

        # Human-readable advisor rendering: Company Name (TICKER) ... 3.12%
        pattern = re.compile(r"\(([A-Za-z0-9.\-/]{1,20})\).{0,500}?([0-9]+(?:\.[0-9]+)?)\s*%", re.I)
        for match in pattern.finditer(decoded):
            symbol = match.group(1).strip().upper()
            try:
                weight = float(match.group(2))
            except ValueError:
                continue
            if cls._valid_holding(symbol, weight):
                found.setdefault(symbol, weight)

        # Common embedded JSON/state shapes used by Vanguard applications.
        json_patterns = [
            re.compile(r'"(?:ticker|symbol)"\s*:\s*"([^"\\]+)".{0,500}?"(?:percentWeight|weight|percent|percentOfFund)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)%?"?', re.I),
            re.compile(r'"(?:percentWeight|weight|percent|percentOfFund)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)%?"?.{0,500}?"(?:ticker|symbol)"\s*:\s*"([^"\\]+)"', re.I),
        ]
        for idx, jp in enumerate(json_patterns):
            for match in jp.finditer(decoded):
                symbol, raw_weight = (match.group(1), match.group(2)) if idx == 0 else (match.group(2), match.group(1))
                symbol = symbol.strip().upper()
                try:
                    weight = float(raw_weight)
                except ValueError:
                    continue
                if cls._valid_holding(symbol, weight):
                    found.setdefault(symbol, weight)
        return [{"symbol": symbol, "percent": weight} for symbol, weight in found.items()]

    @staticmethod
    def _valid_holding(symbol: str, weight: float) -> bool:
        return bool(symbol and symbol not in {"NAN", "--", "-", "CASH", "USD"} and "CASH" not in symbol and 0 < weight <= 100)

    def _fetch_vanguard_json(self, ticker: str) -> tuple[list[dict[str, Any]], str | None, str]:
        url = f"https://investor.vanguard.com/investment-products/etfs/profile/api/{ticker.upper()}/portfolio-holding/stock?start=1&count=50000"
        response = self._get(url, headers=self.VANGUARD_BROWSER_HEADERS)
        content_type = str(response.headers.get("Content-Type") or "")
        try:
            payload = response.json()
        except ValueError as exc:
            preview = re.sub(r"\s+", " ", response.text[:120]).strip()
            raise IssuerHoldingsError(f"VANGUARD_JSON_INVALID:content_type={content_type}:body={preview!r}:{exc}") from exc
        entities = (((payload.get("fund") or {}).get("entity")) or []) if isinstance(payload, dict) else []
        rows: list[dict[str, Any]] = []
        for item in entities:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("ticker") or "").strip().upper()
            raw_weight = item.get("percentWeight")
            if not symbol or symbol in {"NAN", "--", "-", "CASH", "USD"} or "CASH" in symbol:
                continue
            try:
                weight = float(str(raw_weight or "").replace("%", "").replace(",", "").strip())
            except ValueError:
                continue
            if weight > 0:
                rows.append({"symbol": symbol, "percent": weight})
        as_of_raw = str(payload.get("asOfDate") or "") if isinstance(payload, dict) else ""
        as_of_match = re.match(r"(\d{4}-\d{2}-\d{2})", as_of_raw)
        as_of = as_of_match.group(1) if as_of_match else None
        print(f"VANGUARD_JSON_DIAGNOSTIC ticker={ticker.upper()} status={response.status_code} content_type={content_type} holdings={len(rows)} as_of={as_of}")
        if not rows:
            raise IssuerHoldingsError("VANGUARD_JSON_NO_HOLDINGS")
        if as_of is None:
            raise IssuerHoldingsError("VANGUARD_JSON_AS_OF_MISSING")
        return rows, as_of, url

    def _fetch_ishares_csv(self, product_url: str, ticker: str) -> tuple[list[dict[str, Any]], str | None]:
        base = product_url.rstrip("/")
        csv_url = f"{base}/1467271812596.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
        response = self._get(csv_url)
        text = response.text
        lines = text.splitlines()
        header_idx = next((idx for idx, line in enumerate(lines) if "TICKER" in line.upper() and "WEIGHT" in line.upper()), None)
        if header_idx is None:
            raise IssuerHoldingsError("ISHARES_CSV_HEADER_NOT_FOUND")
        frame = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
        return self._normalize_table(frame), self._extract_date(text)

    def _fetch_ishares_ucits_html(self, url: str) -> tuple[list[dict[str, Any]], str | None]:
        response = self._get(url)
        text = response.text
        tables = pd.read_html(io.StringIO(text))
        candidates: list[tuple[int, list[dict[str, Any]]]] = []
        for table in tables:
            normalized = self._normalize_table(table)
            if normalized:
                cols = " ".join(str(c).lower() for c in table.columns)
                candidates.append((len(normalized) + (10000 if "issuer ticker" in cols and "weight" in cols else 0), normalized))
        if not candidates:
            raise IssuerHoldingsError("ISHARES_UCITS_HOLDINGS_TABLE_NOT_FOUND")
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
            try:
                weight = float(str(row.get(weight_col) or "").replace("%", "").replace(",", "").strip())
            except ValueError:
                continue
            if weight > 0:
                rows.append({"symbol": symbol, "percent": weight})
        return rows

    @staticmethod
    def _extract_date(text: str) -> str | None:
        patterns = [r"(?:as of|holdings as of|daily holdings .*? as of)\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", r"(?:as of|holdings as of|daily holdings \(%\) as of)\s*(\d{1,2}/\d{1,2}/\d{4})", r"(?:as of|holdings as of)\s*(\d{4}-\d{2}-\d{2})", r"(?:as of|holdings as of)\s*(\d{1,2}/[A-Za-z]{3,9]/\d{4})"]
        dates: list[datetime] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = match.group(1)
                for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d/%b/%Y", "%d/%B/%Y"):
                    try:
                        dates.append(datetime.strptime(value, fmt)); break
                    except ValueError:
                        pass
        return max(dates).date().isoformat() if dates else None

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()