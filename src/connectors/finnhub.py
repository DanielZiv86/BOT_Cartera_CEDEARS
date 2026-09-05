from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


class FinnhubError(RuntimeError):
    pass


class FinnhubRateLimit(FinnhubError):
    pass


class FinnhubAccessDenied(FinnhubError):
    pass


@dataclass
class FinnhubConnector:
    token: str | None = None
    timeout: int = 30
    min_interval_seconds: float = 0.08
    max_retries: int = 5
    default_rate_limit_sleep_seconds: float = 60.0

    def __post_init__(self) -> None:
        self.token = self.token or os.getenv("FINNHUB_TOKEN", "")
        self.base_url = "https://finnhub.io/api/v1"
        self._cache: dict[tuple[str, tuple[tuple[str, Any], ...]], Any] = {}
        self._last_call = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _get(self, endpoint: str, **params: Any) -> Any:
        if not self.token:
            raise FinnhubAccessDenied("FINNHUB_TOKEN_NOT_CONFIGURED")
        key = (endpoint, tuple(sorted(params.items())))
        if key in self._cache:
            return self._cache[key]

        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    f"{self.base_url}{endpoint}",
                    params={**params, "token": self.token},
                    timeout=self.timeout,
                    headers={"User-Agent": "CEDEAR-Valuation-Engine/1.1"},
                )
                self._last_call = time.monotonic()
                if response.status_code in {401, 403}:
                    raise FinnhubAccessDenied(f"FINNHUB_ACCESS_{response.status_code}")
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after is not None else self.default_rate_limit_sleep_seconds
                    except ValueError:
                        delay = self.default_rate_limit_sleep_seconds
                    last_error = FinnhubRateLimit("FINNHUB_RATE_LIMIT_429")
                    if attempt >= self.max_retries - 1:
                        raise last_error
                    time.sleep(max(delay, self.default_rate_limit_sleep_seconds))
                    continue
                response.raise_for_status()
                data = response.json()
                self._cache[key] = data
                return data
            except FinnhubAccessDenied:
                raise
            except FinnhubRateLimit as exc:
                last_error = exc
                if attempt >= self.max_retries - 1:
                    break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
        raise FinnhubError(str(last_error or "FINNHUB_REQUEST_FAILED"))

    def price_target(self, symbol: str) -> dict[str, Any]:
        data = self._get("/stock/price-target", symbol=symbol)
        return data if isinstance(data, dict) else {}

    def recommendation_trends(self, symbol: str) -> list[dict[str, Any]]:
        data = self._get("/stock/recommendation", symbol=symbol)
        return data if isinstance(data, list) else []

    def basic_financials(self, symbol: str) -> dict[str, Any]:
        data = self._get("/stock/metric", symbol=symbol, metric="all")
        return data if isinstance(data, dict) else {}

    def quote(self, symbol: str) -> dict[str, Any]:
        data = self._get("/quote", symbol=symbol)
        return data if isinstance(data, dict) else {}

    def etf_profile(self, symbol: str) -> dict[str, Any]:
        data = self._get("/etf/profile", symbol=symbol)
        return data if isinstance(data, dict) else {}

    def etf_holdings(self, symbol: str) -> dict[str, Any]:
        data = self._get("/etf/holdings", symbol=symbol)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def retrieved_at() -> str:
        return datetime.now(timezone.utc).isoformat()
