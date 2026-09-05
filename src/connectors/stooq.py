from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

import pandas as pd
import requests

from .base import PriceQuote


US_MARKET_MARKERS = ("NYSE", "NASDAQ", "CBOE", "NEW YORK")


class StooqPriceConnector:
    name = "stooq"
    provider_tier = "APPROVED_MARKET_DATA_FALLBACK"

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 BOT_Cartera_CEDEARS/1.0"})

    @staticmethod
    def _transport_symbol(symbol: str, market: str | None) -> str:
        value = symbol.strip()
        upper = (market or "").upper()
        if any(marker in upper for marker in US_MARKET_MARKERS) and "." not in value:
            return f"{value}.US"
        return value

    def get_last_close(self, symbol: str, market: str | None = None) -> PriceQuote | None:
        transport_symbol = self._transport_symbol(symbol, market)
        end = date.today()
        start = end - timedelta(days=20)
        url = "https://stooq.com/q/d/l/"
        response = self.session.get(
            url,
            params={
                "s": transport_symbol.lower(),
                "d1": start.strftime("%Y%m%d"),
                "d2": end.strftime("%Y%m%d"),
                "i": "d",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        text = response.text.strip()
        if not text or text.lower().startswith("no data"):
            return None

        frame = pd.read_csv(StringIO(text))
        if frame.empty or "Date" not in frame.columns or "Close" not in frame.columns:
            return None
        frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
        frame = frame.dropna(subset=["Date", "Close"])
        frame = frame[frame["Close"] > 0]
        if frame.empty:
            return None

        latest = frame.iloc[-1]
        prior_close = float(frame.iloc[-2]["Close"]) if len(frame) > 1 else None
        close_date = pd.to_datetime(latest["Date"]).date()

        return PriceQuote(
            symbol=transport_symbol,
            close=float(latest["Close"]),
            close_date=close_date,
            prior_close=prior_close,
            currency=None,
            source=self.name,
            source_ref=response.url,
            provider_tier=self.provider_tier,
            confidence="MEDIUM_FALLBACK",
        )
