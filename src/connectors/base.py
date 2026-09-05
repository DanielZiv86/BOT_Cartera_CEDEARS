from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    close: float
    close_date: date
    prior_close: float | None
    currency: str | None
    source: str
    source_ref: str
    provider_tier: str
    confidence: str


class PriceConnector(Protocol):
    name: str
    provider_tier: str

    def get_last_close(
        self,
        symbol: str,
        market: str | None = None,
    ) -> PriceQuote | None:
        ...
