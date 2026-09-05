from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


class TrackerDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackerSnapshot:
    ticker: str
    nav: float | None
    nav_date: str | None
    market_price: float | None
    market_price_date: str | None
    premium_discount_pct: float | None
    source_ref: str
    provider: str
    source_tier: str = "ISSUER_OFFICIAL"


class NonEquityTrackerConnector:
    def __init__(self, tracker_policy: dict[str, Any], timeout: int = 30) -> None:
        self.policy = tracker_policy or {}
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CEDEAR-NonEquity-Tracker/1.1"})

    @staticmethod
    def _money(text: str) -> float | None:
        cleaned = text.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _normalize_date(text: str | None) -> str | None:
        if not text:
            return None
        raw = re.sub(r"\s+", " ", text.strip())
        for fmt in ("%b %d %Y", "%b %d, %Y", "%Y-%m-%d", "%d %b %Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                pass
        return None

    @staticmethod
    def _visible_text(raw_html: str) -> str:
        text = html_lib.unescape(raw_html or "")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _get_html(self, url: str) -> str:
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    def _parse_ishares(self, ticker: str, cfg: dict[str, Any], html: str) -> TrackerSnapshot:
        nav = None
        nav_date = None
        market = None
        market_date = None
        premium = None
        text = self._visible_text(html)

        # iShares renders some values through nested markup/entities. Parse the
        # normalized visible text rather than relying on raw HTML adjacency.
        nav_patterns = [
            r"NAV\s+as\s+of\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4})\s+\$+\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
            r"NAV\s+as\s+of\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4}).{0,120}?([0-9][0-9,]*(?:\.[0-9]+)?)",
        ]
        for pattern in nav_patterns:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                nav_date = self._normalize_date(m.group(1))
                nav = self._money(m.group(2))
                if nav and nav > 0:
                    break

        m = re.search(
            r"Closing\s+Price\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?).*?as\s+of\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4})",
            text,
            re.I | re.S,
        )
        if m:
            market = self._money(m.group(1))
            market_date = self._normalize_date(m.group(2))

        m = re.search(r"Premium/Discount\s+(-?[0-9]+(?:\.[0-9]+)?)", text, re.I | re.S)
        if m:
            try:
                premium = float(m.group(1))
            except ValueError:
                premium = None

        if nav is None:
            raise TrackerDataError(f"ISSUER_NAV_PARSE_FAILED:{ticker}")

        return TrackerSnapshot(
            ticker=ticker,
            nav=nav,
            nav_date=nav_date,
            market_price=market,
            market_price_date=market_date,
            premium_discount_pct=premium,
            source_ref=str(cfg.get("issuer_url")),
            provider=str(cfg.get("provider") or "iShares"),
        )

    def _parse_ssga(self, ticker: str, cfg: dict[str, Any], html: str) -> TrackerSnapshot:
        nav = None
        nav_date = None
        market = None
        market_date = None
        premium = None

        m = re.search(r"Fund\s+Net\s+Asset\s+Value\s+as\s+of\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{4}).{0,600}?NAV.{0,120}?\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", html, re.I | re.S)
        if not m:
            m = re.search(r"NAV.{0,500}?\$\s*([0-9][0-9,]*(?:\.[0-9]+)?).{0,180}?as\s+of\s+([A-Za-z]{3}\s+\d{1,2}\s+\d{4})", html, re.I | re.S)
            if m:
                nav = self._money(m.group(1))
                nav_date = self._normalize_date(m.group(2))
        else:
            nav_date = self._normalize_date(m.group(1))
            nav = self._money(m.group(2))

        m = re.search(r"Closing\s+Price.{0,250}?\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", html, re.I | re.S)
        if m:
            market = self._money(m.group(1))

        m = re.search(r"Premium/Discount.{0,300}?(-?[0-9]+(?:\.[0-9]+)?)", html, re.I | re.S)
        if m:
            try:
                premium = float(m.group(1))
            except ValueError:
                premium = None

        if nav is None:
            raise TrackerDataError(f"ISSUER_NAV_PARSE_FAILED:{ticker}")

        return TrackerSnapshot(
            ticker=ticker,
            nav=nav,
            nav_date=nav_date,
            market_price=market,
            market_price_date=market_date,
            premium_discount_pct=premium,
            source_ref=str(cfg.get("issuer_url")),
            provider=str(cfg.get("provider") or "State Street"),
        )

    def fetch(self, ticker: str) -> TrackerSnapshot:
        t = ticker.upper()
        cfg = (self.policy.get("trackers") or {}).get(t)
        if not isinstance(cfg, dict):
            raise TrackerDataError(f"TRACKER_POLICY_NOT_CONFIGURED:{t}")
        url = str(cfg.get("issuer_url") or "").strip()
        if not url:
            raise TrackerDataError(f"ISSUER_URL_MISSING:{t}")
        html = self._get_html(url)
        provider = str(cfg.get("provider") or "").upper()
        if "STATE STREET" in provider or "SPDR" in provider:
            return self._parse_ssga(t, cfg, html)
        return self._parse_ishares(t, cfg, html)

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()
