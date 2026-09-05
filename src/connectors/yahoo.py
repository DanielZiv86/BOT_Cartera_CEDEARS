from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import requests

from .base import PriceQuote


class YahooPriceConnector:
    name = "yahoo"
    provider_tier = "APPROVED_MARKET_DATA_FALLBACK"

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 BOT_Cartera_CEDEARS/1.0"})

    def get_last_close(self, symbol: str, market: str | None = None) -> PriceQuote | None:
        encoded = quote(symbol, safe=".-^")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        response = self.session.get(
            url,
            params={
                "range": "10d",
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None

        timestamps = result.get("timestamp") or []
        quotes = (((result.get("indicators") or {}).get("quote") or [{}])[0])
        closes = quotes.get("close") or []
        valid: list[tuple[int, float]] = []
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            try:
                value = float(close)
            except (TypeError, ValueError):
                continue
            if value > 0:
                valid.append((int(ts), value))

        if not valid:
            return None

        latest_ts, latest_close = valid[-1]
        prior_close = valid[-2][1] if len(valid) > 1 else None
        metadata = result.get("meta") or {}
        currency = metadata.get("currency")
        close_date = datetime.fromtimestamp(latest_ts, tz=timezone.utc).date()

        return PriceQuote(
            symbol=symbol,
            close=latest_close,
            close_date=close_date,
            prior_close=prior_close,
            currency=str(currency) if currency else None,
            source=self.name,
            source_ref=response.url,
            provider_tier=self.provider_tier,
            confidence="HIGH_SECONDARY",
        )
